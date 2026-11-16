#!/usr/bin/env python3
"""Validate opt-in profiles and execute their resolved device lambdas natively.

Requires the release-pinned ESPHome CLI, PyYAML and a C++17 compiler.
Run: python3 tools/test-temperature-curve-per-fan.py
"""
from pathlib import Path
import subprocess
import tempfile
import yaml

ROOT = Path(__file__).resolve().parents[1]
OPTIONS = ["Manual", "Silent", "Balanced", "Aggressive", "Server", "Custom"]


def resolved(path):
    result = subprocess.run(["esphome", "config", str(path)], cwd=ROOT,
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr + result.stdout)
    return yaml.load(result.stdout, Loader=yaml.BaseLoader)


def keyed(config, kind):
    return {item["id"]: item for item in config.get(kind, []) if "id" in item}


def check_config(config):
    selects = keyed(config, "select")
    numbers = keyed(config, "number")
    globals_ = keyed(config, "globals")
    assert set(selects) == {f"fan{i}_profile" for i in range(1, 5)}
    assert len(numbers) == 40
    for i in range(1, 5):
        select = selects[f"fan{i}_profile"]
        assert select["options"] == OPTIONS
        assert select["restore_value"] == "true" and select["optimistic"] == "true"
        assert select["initial_option"] == "Manual" and select["update_interval"] == "4294967295ms"
        assert "lambda" not in select
        for kind in ("temp", "speed"):
            for point in range(1, 6):
                number = numbers[f"fan{i}_curve_{kind}{point}"]
                assert number["restore_value"] == "true" and number["mode"] == "BOX"
        # Hardware and override globals are allowed, but the profile module
        # must not introduce a separately persisted automatic/manual flag.
        assert f"fan{i}_profile_mode" not in globals_
        assert f"auto_control_fan{i}" not in keyed(config, "switch")
        assert not any(k in keyed(config, "fan")[f"fan{i}"]
                       for k in ("on_speed_set", "on_turn_on", "on_turn_off"))
    assert not any(k.startswith("curve_") for k in globals_)
    assert "curve_output_value" not in keyed(config, "sensor")
    ticks = [entry for entry in config["interval"] if entry["interval"] == "10s"]
    assert any([a.get("script.execute", {}).get("id") for a in entry["then"]] ==
               [f"fan{i}_apply_profile" for i in range(1, 5)] for entry in ticks)
    print("PASS standalone config: four restored selectors, 40 numbers, independent tick, no shared controller")


def check_behavior(config):
    """Compile actual resolved lambdas; model the relevant ESPHome call order."""
    selects, numbers, scripts = (keyed(config, k) for k in ("select", "number", "script"))
    boot = [a["lambda"] for item in config["esphome"]["on_boot"]
            for a in item["then"] if "lambda" in a]
    source = ['#include <cassert>', '#include <cmath>', '#include <string>',
              '#include <array>', '#include <limits>', '#define id(x) x', '''
struct Number;
struct NumberCall { Number *number; float value; void set_value(float x) { value=x; } void perform(); };
struct Number { float state; void (*changed)() = nullptr; NumberCall make_call() { return {this,state}; } };
void NumberCall::perform() { number->state=value; if(number->changed) number->changed(); }
struct Fan;
struct FanCall { Fan *fan; bool state; int speed=-1; void set_speed(int x) { speed=x; } void perform(); };
struct Fan { bool state=false; int speed=0; FanCall turn_on() { return {this,true}; } FanCall turn_off() { return {this,false}; } };
void FanCall::perform() { fan->state=state; if(speed>=0) fan->speed=speed; }
void choose(int fan, std::string x);
struct Profile;
struct ProfileCall { Profile *profile; std::string option; void set_option(std::string x) { option=x; } void perform(); };
struct Profile { int fan; std::string state="Manual", saved="Manual";
  std::string current_option() { return state; }
  void publish_state(std::string x) { state=x; }
  ProfileCall make_call() { return {this,{}}; }
};
void ProfileCall::perform() { choose(profile->fan,option); profile->publish_state(option); profile->saved=option; }
struct Script { void (*apply)(); void execute() { apply(); } };
Number fancontroller_temperature{30};
''']
    own = []
    for i in range(1, 5):
        source.extend([f'Profile fan{i}_profile{{{i}}}; Fan fan{i};',
                       f'bool fan{i}_profile_ready=false, fan{i}_loading_profile=false, fan{i}_curve_warning=false;',
                       f'bool usr_override_fan{i}=false; float fan{i}_safety_floor=0;',
                       f'void apply{i}(); Script fan{i}_apply_profile{{apply{i}}};'])
        for point in range(1, 6):
            for kind in ("temp", "speed"):
                key = f"fan{i}_curve_{kind}{point}"
                own.append(key)
                initial = float(numbers[key]["initial_value"])
                source.extend([f'void {key}_changed();',
                               f'Number {key}{{{initial}f,{key}_changed}};'])
    for i in range(1, 5):
        code = selects[f"fan{i}_profile"]["set_action"]["then"][0]["lambda"]
        # ESPHome resolves id(number) as a pointer; our macro uses values.
        source.extend([f'void choose{i}(std::string x) {{', code.replace('set(id(', 'set(&id('), '}',
                       f'void apply{i}() {{', scripts[f"fan{i}_apply_profile"]["then"][0]["lambda"], '}',
                       f'void boot{i}() {{', next(c for c in boot if f'id(fan{i}_profile_ready)' in c),
                       f'apply{i}();', '}'])
        for point in range(1, 6):
            for kind in ("temp", "speed"):
                key = f"fan{i}_curve_{kind}{point}"
                source.extend([f'void {key}_changed() {{', numbers[key]["on_value"][0]["then"][0]["lambda"], '}'])
    source.extend(['void choose(int fan, std::string x) { switch(fan) {'])
    for i in range(1, 5):
        source.append(f'case {i}: choose{i}(x); break;')
    source.extend(['} }', 'std::array<float,40> snapshot() { return {',
                   ','.join(key+'.state' for key in own), '}; }', '''
void tick() { apply1(); apply2(); apply3(); apply4(); }
void pick(Profile &profile, std::string option) { auto call=profile.make_call(); call.set_option(option); call.perform(); }
void edit(Number &number, float value) { auto call=number.make_call(); call.set_value(value); call.perform(); }
int main() {
// Numbers restore before the late boot hook. Do not select Custom or drive fans.
edit(fan2_curve_speed3,60); assert(fan2_profile.state=="Manual" && !fan2.state);
boot1(); boot2(); boot3(); boot4(); tick();
assert(!fan1.state && !fan2.state && !fan3.state && !fan4.state);
// Independent control and user edits: automatic edits become persisted Custom.
pick(fan1_profile,"Silent"); pick(fan2_profile,"Balanced");
assert(fan1.speed==30 && fan2.speed==50);
edit(fan1_curve_speed3,80); assert(fan1_profile.state=="Custom" && fan1_profile.saved=="Custom");
assert(fan1.speed==50 && fan2.speed==50 && fan2_curve_speed3.state==50);
pick(fan1_profile,"Manual"); edit(fan1_curve_speed3,90); tick();
assert(fan1_profile.state=="Manual" && fan1.speed==50);
pick(fan1_profile,"Custom"); assert(fan1.speed==55);
// Automatic mode survives HA writes, first-boot speed writes and recovery bumps.
pick(fan1_profile,"Balanced"); auto write=fan1.turn_on(); write.set_speed(100); write.perform();
assert(fan1_profile.state=="Balanced"); tick(); assert(fan1.speed==50);
fan1.turn_off().perform(); tick(); assert(fan1.state && fan1.speed==50);
// Fixed speed and fixed off require explicit Manual.
pick(fan1_profile,"Manual"); write=fan1.turn_on(); write.set_speed(43); write.perform();
fancontroller_temperature.state=50; tick(); assert(fan1.speed==43);
fan1.turn_off().perform(); tick(); assert(!fan1.state);
// Regression: paused at 0%, Manual, then preset must resume at higher temps.
fancontroller_temperature.state=18; pick(fan1_profile,"Balanced"); assert(!fan1.state);
pick(fan1_profile,"Manual"); pick(fan1_profile,"Balanced");
fancontroller_temperature.state=50; tick(); assert(fan1.state && fan1.speed==100);
// Safety floors and temporary physical overrides never select Manual.
fancontroller_temperature.state=30; fan1_safety_floor=90; pick(fan1_profile,"Silent"); assert(fan1.speed==90);
usr_override_fan1=true; pick(fan1_profile,"Server"); assert(fan1.speed==90);
usr_override_fan1=false; fan1_safety_floor=0; tick(); assert(fan1.speed==75 && fan1_profile.state=="Server");
// A safety floor must not undo a curve's intentional zero.
fan1_safety_floor=90; fancontroller_temperature.state=18; pick(fan1_profile,"Balanced"); assert(!fan1.state);
fan1_safety_floor=0; fancontroller_temperature.state=30;
'''])
    # Every preset on every channel: verify output at 30C and isolation.
    for i in range(1, 5):
        for name, speed in [("Silent", 30), ("Balanced", 50), ("Aggressive", 67), ("Server", 75)]:
            source.extend(['{ auto before=snapshot();', f'pick(fan{i}_profile,"{name}");',
                           f'assert(fan{i}.state && fan{i}.speed=={speed});',
                           'auto after=snapshot(); for(int j=0;j<40;j++) {',
                           f'if(j/10 != {i-1}) assert(before[j]==after[j]);', '} }'])
    source.extend(['''
// Boot restores the selector and edited points without reapplying named presets.
pick(fan1_profile,"Balanced"); edit(fan1_curve_speed3,46);
fan1_profile_ready=false; edit(fan1_curve_speed3,46);
fan1_profile.publish_state(fan1_profile.saved); boot1();
assert(fan1_profile.state=="Custom" && fan1.speed==46 && fan1_curve_speed3.state==46);
pick(fan2_profile,"Manual"); fan2.turn_off().perform(); fan2_profile_ready=false;
fan2_profile.publish_state(fan2_profile.saved); boot2(); tick(); assert(!fan2.state);
// Out-of-order points, endpoints, duplicate temperatures and invalid samples.
pick(fan1_profile,"Balanced"); edit(fan1_curve_temp1,32);
assert(fan1_curve_warning && fan1.speed==50);
pick(fan1_profile,"Balanced"); fancontroller_temperature.state=-5; tick(); assert(!fan1.state);
fancontroller_temperature.state=100; tick(); assert(fan1.speed==100);
edit(fan1_curve_temp2,20); fancontroller_temperature.state=20; tick(); assert(!fan1.state);
fancontroller_temperature.state=30; tick(); assert(fan1.speed==50 && fan1_curve_warning);
fancontroller_temperature.state=std::numeric_limits<float>::quiet_NaN(); tick(); assert(fan1.speed==50);
fancontroller_temperature.state=std::numeric_limits<float>::infinity(); tick(); assert(fan1.speed==50);
fancontroller_temperature.state=30; edit(fan1_curve_speed3,std::numeric_limits<float>::quiet_NaN());
assert(fan1.speed==50 && fan1_curve_warning);
}
'''])
    with tempfile.TemporaryDirectory(prefix="per-fan-test-") as directory:
        path, binary = Path(directory)/"profiles.cpp", Path(directory)/"profiles"
        path.write_text('\n'.join(source))
        subprocess.run(['c++', '-std=c++17', str(path), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
    print("PASS device lambdas: all 16 presets, isolation, Custom/Manual, boot restoration, pause/resume, external writes, overrides, floors and invalid inputs")



def check_integrations():
    # Resolve realistic combinations against local modules, including an
    # alternate sensor and the safety/physical-override integrations.
    with tempfile.TemporaryDirectory(prefix="per-fan-", dir=ROOT/".test-build") as directory:
        path = Path(directory)/"combined.yaml"
        path.write_text("""packages:
  base: !include ../with-temperature-curve-per-fan-rev-3.3.yaml
  stall_guard: !include ../../modules/stall_guard.yaml
  buttons: !include ../../modules/usr_buttons_mode.yaml
  fallback: !include ../../modules/fallback_mode.yaml
substitutions:
  temperature_sensor_id: cabinet_temperature
sensor:
  - platform: template
    id: cabinet_temperature
    lambda: return 30.0f;
""")
        config = resolved(path)
        scripts = keyed(config, "script")
        for i in range(1, 5):
            code = scripts[f"fan{i}_apply_profile"]["then"][0]["lambda"]
            assert "id(cabinet_temperature).state" in code
        assert "fan1_profile" in keyed(config, "select")
        # A stock adopted build can still opt into the original linear
        # controller without colliding with profiles injected by firmware.
        path.write_text("""packages:
  base: !include ../../fancontroller-rev3.3-esp32s2.yaml
  linear: !include ../../modules/temperature_linear.yaml
""")
        adopted = resolved(path)
        assert "auto_control_fan1" in keyed(adopted, "switch")
        assert "fan1_profile" not in keyed(adopted, "select")
    print("PASS integrations: external sensor, Stall Guard, Fallback, USR mode and stock adoption with Linear")


def main():
    subprocess.run(['python3', 'tools/localize-examples.py'], cwd=ROOT, check=True)
    config = resolved(Path('.test-build/with-temperature-curve-per-fan-rev-3.3.yaml'))
    check_config(config)
    check_behavior(config)
    check_integrations()
    # Discover revisions rather than hard-coding their count. Stock configs
    # and hardware-only examples must not acquire this optional controller.
    configs = sorted(p for p in ROOT.glob('fancontroller-rev*.yaml') if '.qc.' not in p.name)
    assert configs, 'No production configurations found'
    for path in configs:
        stock = resolved(path)
        assert not any(k.startswith('fan1_curve_') for k in keyed(stock, 'number')), path
        assert 'fan1_profile' not in keyed(stock, 'select'), path
    print(f'PASS {len(configs)} standard/factory configs: optional profiles are absent')
    shared = resolved(Path('.test-build/with-temperature-curve-rev-3.1.yaml'))
    assert 'curve_output_value' in keyed(shared, 'sensor')
    assert 'fan1_profile' not in keyed(shared, 'select')
    print('PASS existing shared curve remains standalone')


if __name__ == '__main__':
    main()
