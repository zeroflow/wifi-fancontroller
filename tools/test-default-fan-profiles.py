#!/usr/bin/env python3
"""Check the resolved shipping configs, not just the package source text.

Run with the release-pinned ESPHome CLI and PyYAML on PATH, as in the
Validate workflow: python3 tools/test-default-fan-profiles.py
"""

from pathlib import Path
import subprocess
import tempfile

import yaml


ROOT = Path(__file__).resolve().parents[1]
PRESETS = {"silent", "balanced", "aggressive", "server"}
CURVE_NUMBERS = {
    f"curve_{kind}{index}"
    for kind in ("temp", "speed")
    for index in range(1, 6)
}
AUTO_SWITCHES = {f"auto_control_fan{index}" for index in range(1, 5)}


def resolved(path):
    result = subprocess.run(
        ["esphome", "config", str(path)], cwd=ROOT,
        capture_output=True, text=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr + result.stdout)
    # The CLI has already resolved !include/!extend. BaseLoader treats the
    # remaining ESPHome scalars (including !lambda) as data, never as code.
    return yaml.load(result.stdout, Loader=yaml.BaseLoader)


def check_profiles(path, expected_restore_mode):
    config = resolved(path)
    switches = {item["id"]: item for item in config.get("switch", [])}
    assert AUTO_SWITCHES <= switches.keys(), f"{path}: missing auto controls"
    for switch_id in AUTO_SWITCHES:
        assert switches[switch_id]["restore_mode"] == expected_restore_mode, (
            f"{path}: unexpected initial state for {switch_id}"
        )

    numbers = {item["id"]: item for item in config.get("number", [])}
    assert CURVE_NUMBERS <= numbers.keys(), f"{path}: missing curve tuning"
    assert all(numbers[key]["restore_value"] == "true" for key in CURVE_NUMBERS)
    assert all(numbers[key]["mode"] == "BOX" for key in CURVE_NUMBERS)

    profiles = {item["id"]: item for item in config.get("select", [])}
    profile = profiles["fan_profile"]
    expected_options = ["Silent", "Balanced", "Aggressive", "Server", "Custom"]
    assert profile["options"] == expected_options
    assert profile.get("entity_category", "") == ""
    assert "lambda" in profile and "restore_value" not in profile
    assert "set_action" in profile
    assert not any(key.endswith("_control_mode") for key in profiles), (
        f"{path}: duplicate fan-mode dropdowns are exposed"
    )
    if expected_restore_mode == "RESTORE_DEFAULT_OFF":
        assert profile["internal"] == "true"
        expected_profiles = {f"fan{i}_profile" for i in range(1, 5)}
        assert {key for key, value in profiles.items() if value.get("internal", "false") == "false"} == expected_profiles
        for i in range(1, 5):
            assert profiles[f"fan{i}_profile"]["options"] == ["Manual", "Silent", "Balanced", "Aggressive", "Server", "Custom"]
            for kind in ("temp", "speed"):
                for point in range(1, 6):
                    number = numbers[f"fan{i}_curve_{kind}{point}"]
                    assert number["restore_value"] == "true" and number["mode"] == "BOX"
                    assert number.get("entity_category") == "config"
            assert switches[f"auto_control_fan{i}"]["internal"] == "true"
        public_numbers = [value for value in numbers.values() if value.get("internal", "false") == "false"]
        assert len(public_numbers) == 40, f"{path}: expected 40 independent curve settings"
        assert all(numbers[key]["internal"] == "true" for key in CURVE_NUMBERS)
        globals_by_id = {item["id"]: item for item in config["globals"]}
        assert all(globals_by_id[f"fan{i}_profile_mode"]["restore_value"] == "true" for i in range(1, 5))
    else:
        assert not any(key.startswith("fan1_curve_") for key in numbers)

    buttons = {item["id"]: item for item in config.get("button", [])}
    for preset in PRESETS:
        button_id = f"curve_preset_{preset}"
        assert button_id in buttons, f"{path}: missing {button_id}"
        button = buttons[button_id]
        expected_internal = "true" if expected_restore_mode == "RESTORE_DEFAULT_OFF" else "false"
        assert button.get("internal", "false") == expected_internal, (
            f"{path}: duplicate preset-button visibility is incorrect"
        )
        assert len(button["on_press"]) == 1, f"{path}: duplicate preset actions"
        actions = button["on_press"][0]["then"]
        updated = [action["number.set"]["id"] for action in actions if "number.set" in action]
        assert len(updated) == 10 and set(updated) == CURVE_NUMBERS, (
            f"{path}: {button_id} must set every curve point before applying it"
        )
        assert actions[-2]["component.update"]["id"] == "curve_output_value"
        assert actions[-1]["component.update"]["id"] == "fan_profile"
        assert all("number.set" in action for action in actions[:10])
    print(f"PASS {path}: four presets, persistent tuning, {expected_restore_mode}")
    return config


def check_profile_detection(config):
    """Run the actual device lambda against the preset actions and custom edits."""
    profile = next(item for item in config["select"] if item["id"] == "fan_profile")
    buttons = {item["id"]: item for item in config["button"]}
    source = [
        "#include <cassert>", "#include <cmath>", "#include <limits>",
        "#include <optional>", "#include <string>", "#define id(x) x",
        "struct Number { float state = 0; };",
        "bool curve_profile_custom = false;",
        "using std::optional;",
        "struct Profile { bool known = false; std::string value;",
        "bool has_state() { return known; }",
        "std::string current_option() { return value; } };",
        "Profile fan_profile;",
        "Number " + ", ".join(sorted(CURVE_NUMBERS)) + ";",
        "std::optional<std::string> detect_profile() {",
        profile["lambda"], "}", "int main() {",
    ]
    for preset in ["Silent", "Balanced", "Aggressive", "Server"]:
        actions = buttons[f"curve_preset_{preset.lower()}"]["on_press"][0]["then"]
        for action in actions:
            if "number.set" in action:
                number = action["number.set"]
                source.append(f'{number["id"]}.state = {float(number["value"])}f;')
        source.append(f'assert(detect_profile().value() == "{preset}");')
        source.extend([
            "curve_profile_custom = true;",
            'assert(detect_profile().value() == "Custom");',
            "curve_profile_custom = false;",
        ])
    source.extend([
        'fan_profile.known = true; fan_profile.value = "Server";',
        "assert(!detect_profile().has_value());",
        "curve_speed5.state -= 1;",
        'assert(detect_profile().value() == "Custom");',
        "curve_temp1.state = std::numeric_limits<float>::quiet_NaN();",
        'assert(detect_profile().value() == "Custom");',
        "}",
    ])
    with tempfile.TemporaryDirectory(prefix="fan-profile-test-") as directory:
        path = Path(directory) / "profile.cpp"
        binary = Path(directory) / "profile-test"
        path.write_text("\n".join(source))
        subprocess.run(["c++", "-std=c++17", str(path), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
    print("PASS profile detection: all presets, custom edits, explicit Custom, invalid values")


def check_independent_profiles(config):
    """Execute resolved device lambdas to check isolation, migration and manual edits."""
    profiles = {item["id"]: item for item in config["select"]}
    fans = {item["id"]: item for item in config["fan"]}
    numbers = {item["id"]: item for item in config["number"]}
    scripts = {item["id"]: item for item in config["script"]}
    output = next(item for item in config["output"] if item["id"] == "curve_proxy_output")
    sensor = next(item for item in config["sensor"] if item["id"] == "curve_output_value")
    boot_lambdas = [action["lambda"] for boot in config["esphome"]["on_boot"]
                    for action in boot["then"] if "lambda" in action]
    source = [
        "#include <cassert>", "#include <cmath>", "#include <string>",
        "#include <optional>", "#include <functional>", "#include <vector>", "#include <array>",
        "#define id(x) x", "using std::optional;",
        "bool curve_profile_custom = false, curve_config_warning = false;",
        "bool curve_user_controls_ready = false, curve_loading_profile = false, curve_applying_output = false;",
        "struct Number; struct NumberCall { Number *number; float value; void set_value(float x) { value = x; } void perform(); };",
        "struct Number { float state = 0; void (*changed)() = nullptr; NumberCall make_call() { return {this, state}; } };",
        "void NumberCall::perform() { number->state = value; if (number->changed) number->changed(); }",
        "Number " + ", ".join(sorted(CURVE_NUMBERS)) + ";",
        "Number fancontroller_temperature{30};",
        "struct Switch { bool state = false; void turn_on() { state = true; } void turn_off() { state = false; } };",
        "Switch auto_control_fan1, auto_control_fan2, auto_control_fan3, auto_control_fan4;",
        "struct Fan; struct Call { Fan *fan; bool state; int speed = -1; void set_speed(int x) { speed = x; } void perform(); };",
        "struct Fan { bool state = false; int speed = 0; void (*on)(); void (*off)(); void (*speed_set)(int);",
        "Call turn_on() { return {this, true}; } Call turn_off() { return {this, false}; } };",
        "void Call::perform() { bool changed = fan->state != state; int old_speed = fan->speed; fan->state = state;",
        "if (speed >= 0) fan->speed = speed; if (changed) { if (state) fan->on(); else fan->off(); }",
        "if (fan->speed != old_speed) fan->speed_set(fan->speed); }",
        "void choose_profile(int fan, std::string x); std::optional<std::string> detect_profile(int fan);",
        "struct ProfileCall { int fan; std::string option; void set_option(std::string x) { option = x; } void perform() { choose_profile(fan, option); } };",
        "struct Profile { int fan; bool known = false; std::string value; bool has_state() { return known; }",
        "std::string current_option() { return value; } void update() { auto x=detect_profile(fan); if(x) { value=*x; known=true; } }",
        "ProfileCall make_call() { return {fan, {}}; } };",
        "std::vector<std::function<void()>> deferred;",
        "void flush_deferred() { auto callbacks=std::move(deferred); deferred.clear(); for(auto callback:callbacks) callback(); }",
        "struct Output { void update(); void defer(std::function<void()> callback) { deferred.push_back(callback); } }; Output curve_output_value;",
        "struct Script { void (*apply)(); void execute() { apply(); } };",
    ]
    own_numbers = []
    for i in range(1, 5):
        source.extend([
            f"int fan{i}_profile_mode = -1;",
            f"Profile fan{i}_profile{{{i}}};",
            f"void fan{i}_on(); void fan{i}_off(); void fan{i}_speed(int x);",
            f"Fan fan{i}{{false, 0, fan{i}_on, fan{i}_off, fan{i}_speed}};",
            f"bool usr_override_fan{i} = false; float fan{i}_safety_floor = 0;",
            f"void apply_fan{i}(); Script fan{i}_apply_profile{{apply_fan{i}}};",
        ])
        for point in range(1, 6):
            for kind in ("temp", "speed"):
                key = f"fan{i}_curve_{kind}{point}"
                own_numbers.append(key)
                source.extend([f"void {key}_changed();", f"Number {key}{{0, {key}_changed}};"])
    source.extend([
        "void write_profiles(float state) {", output["write_action"]["then"][0]["lambda"], "}",
        "void Output::update() { curve_applying_output=true; write_profiles(0); curve_applying_output=false; }",
    ])
    for i in range(1, 5):
        profile = profiles[f"fan{i}_profile"]
        migration = next(code for code in boot_lambdas if f"id(fan{i}_profile_mode) < 0" in code)
        source.extend([
            # ESPHome emits id(number) arguments as pointers; our id macro names
            # reference-like fake objects, so adapt only those helper arguments.
            f"void migrate_fan{i}() {{", migration.replace("copy(id(", "copy(&id("), "}",
            f"std::optional<std::string> detect_fan{i}() {{", profile["lambda"], "}",
            f"void choose_fan{i}(std::string x) {{", profile["set_action"]["then"][0]["lambda"].replace("set(id(", "set(&id("), "}",
            f"void apply_fan{i}() {{", scripts[f"fan{i}_apply_profile"]["then"][0]["lambda"], "}",
        ])
        for action, suffix in (("on_turn_on", "on"), ("on_turn_off", "off"), ("on_speed_set", "speed")):
            source.extend([
                f"void fan{i}_{suffix}({'int x' if suffix == 'speed' else ''}) {{",
                fans[f"fan{i}"][action][0]["then"][0]["lambda"], "}",
            ])
        for point in range(1, 6):
            for kind in ("temp", "speed"):
                key = f"fan{i}_curve_{kind}{point}"
                source.extend([f"void {key}_changed() {{", numbers[key]["on_value"][0]["then"][0]["lambda"], "}"])
    source.extend(["void choose_profile(int fan, std::string x) { switch(fan) {"])
    for i in range(1, 5): source.append(f"case {i}: choose_fan{i}(x); break;")
    source.extend(["} }", "std::optional<std::string> detect_profile(int fan) { switch(fan) {"])
    for i in range(1, 5): source.append(f"case {i}: return detect_fan{i}();")
    source.extend(["} return {}; }", "std::string label(int fan) { switch(fan) {"])
    for i in range(1,5): source.append(f"case {i}: return fan{i}_profile.value;")
    source.extend(["} return {}; }", "std::array<float,40> snapshot() { return {"])
    source.extend([", ".join(f"{key}.state" for key in own_numbers), "}; }", "int main() {"])
    # Seed the old shared Server curve and per-fan automatic choices.
    for point, (temperature, speed) in enumerate([(15,20),(20,30),(25,50),(30,75),(35,100)], 1):
        source.extend([f"curve_temp{point}.state={temperature};", f"curve_speed{point}.state={speed};"])
    source.extend([
        "fan1.state=fan2.state=true; fan1.speed=55; fan2.speed=60;",
        "auto_control_fan1.turn_on(); auto_control_fan2.turn_on();",
        "migrate_fan1(); migrate_fan2(); migrate_fan3(); migrate_fan4();",
        "assert(fan1_profile_mode==1 && fan2_profile_mode==1 && fan3_profile_mode==0 && fan4_profile_mode==0);",
        "assert(fan1_curve_temp4.state==30 && fan4_curve_speed4.state==75);",
        "curve_user_controls_ready=true; curve_output_value.update();",
        "fan1_profile.update(); fan2_profile.update(); assert(fan1_profile.value==\"Server\" && fan2_profile.value==\"Server\");",
        "assert(fan1.speed==75 && fan2.speed==75 && !fan3.state && !fan4.state);",
        'choose_profile(1,"Silent"); assert(fan1.speed==30 && fan2.speed==75);',
        'choose_profile(2,"Balanced"); assert(fan1.speed==30 && fan2.speed==50);',
        "auto edit=fan1.turn_on(); edit.set_speed(43); edit.perform(); flush_deferred();",
        'assert(fan1_profile.value=="Manual" && fan2_profile.value=="Balanced");',
        "fancontroller_temperature.state=35; curve_output_value.update(); assert(fan1.speed==43 && fan2.speed==62);",
        'choose_profile(1,"Custom"); assert(fan1.speed==40 && fan2.speed==62);',
        "auto tune=fan1_curve_speed3.make_call(); tune.set_value(70); tune.perform();",
        "assert(fan1.speed==70 && fan2.speed==62 && fan2_curve_speed3.state==50);",
        "fan1.turn_off().perform(); curve_output_value.update(); assert(!fan1.state && !auto_control_fan1.state);",
        "auto from_off=fan1.turn_on(); from_off.set_speed(37); from_off.perform(); flush_deferred();",
        'assert(fan1_profile.value=="Manual" && fan1.speed==37 && fan2_profile.value=="Balanced");',
        # Curve-generated zero stops do not lose eligibility to restart.
        "curve_loading_profile=true;",
    ])
    for point in range(1,6): source.append(f"fan2_curve_speed{point}.state=0;")
    source.extend([
        "curve_loading_profile=false; curve_output_value.update(); assert(!fan2.state && auto_control_fan2.state);",
        'choose_profile(2,"Balanced"); assert(fan2.state && fan2.speed==62 && fan1.speed==37);',
        "fan2.turn_off().perform();",
        'choose_profile(2,"Aggressive"); assert(!fan2.state);',
        "fan2.turn_on().perform(); flush_deferred(); assert(fan2.state && fan2.speed==85);",
        'assert(fan2_profile.value=="Aggressive" && fan1_profile.value=="Manual");',
        # A restored fan percentage must not change a restored automatic mode.
        "curve_user_controls_ready=false; auto restore=fan2.turn_on(); restore.set_speed(49); restore.perform(); flush_deferred();",
        "assert(fan2_profile_mode==1); curve_user_controls_ready=true;",
        # Migration must never overwrite each fan's saved rules on later boots.
        "fan1_curve_speed3.state=66; migrate_fan1(); assert(fan1_curve_speed3.state==66 && fan1_profile_mode==0);",
        # All preset setters must agree with detection, without touching other curves.
        "for(int fan=1;fan<=4;fan++) for(auto preset : {\"Silent\",\"Balanced\",\"Aggressive\",\"Server\"}) {",
        "auto before=snapshot(); choose_profile(fan,preset); auto after=snapshot(); assert(label(fan)==preset);",
        "for(int point=0;point<40;point++) if(point/10!=fan-1) assert(before[point]==after[point]);",
        "auto detected=detect_profile(fan); assert(!detected.has_value());",  # setter already published correct name
        "}",
        # Explicit Custom keeps its label even if the points match a preset.
        'choose_profile(3,"Custom"); assert(fan3_profile.value=="Custom" && fan3_profile_mode==2);',
        "auto curves=snapshot(); migrate_fan3(); assert(snapshot()==curves);",
        "fan2_safety_floor=90; choose_profile(2,\"Silent\"); assert(fan2.speed==90); fan2_safety_floor=0;",
        "usr_override_fan2=true; choose_profile(2,\"Server\"); assert(fan2.speed==90); usr_override_fan2=false;",
        "}",
    ])
    actions=sensor["on_value"][0]["then"]
    assert actions[0]["lambda"]=="id(curve_applying_output) = true;"
    assert actions[-1]["lambda"]=="id(curve_applying_output) = false;"
    with tempfile.TemporaryDirectory(prefix="fan-profiles-test-") as directory:
        path=Path(directory)/"profiles.cpp"
        binary=Path(directory)/"profiles-test"
        path.write_text("\n".join(source))
        subprocess.run(["c++","-std=c++17",str(path),"-o",str(binary)],check=True)
        subprocess.run([str(binary)],check=True)
    print("PASS independent profiles: migration, 16 preset selections, isolated custom/manual edits, Off, restart eligibility, safety floors")


def main():
    subprocess.run(["python3", "tools/localize-examples.py"], cwd=ROOT, check=True)
    configs = sorted(
        path for path in ROOT.glob("fancontroller-rev*.yaml")
        if ".qc." not in path.name
    )
    assert len(configs) == 12, "Expected six standard and six factory configs"
    for path in configs:
        config = check_profiles(path.relative_to(ROOT), "RESTORE_DEFAULT_OFF")
    check_profile_detection(config)
    check_independent_profiles(config)

    # The shared defaults must not change explicit module users or custom
    # hardware-only builds. These examples resolve against the working tree.
    check_profiles(
        Path(".test-build/with-temperature-curve-rev-3.1.yaml"),
        "RESTORE_DEFAULT_ON",
    )
    hardware_only = resolved(Path(".test-build/basic-rev-3.1.yaml"))
    switch_ids = {item["id"] for item in hardware_only.get("switch", [])}
    assert not AUTO_SWITCHES.intersection(switch_ids), (
        "Hardware-only builds unexpectedly include automatic curve control"
    )
    print("PASS hardware-only build: no automatic curve control added")


if __name__ == "__main__":
    main()
