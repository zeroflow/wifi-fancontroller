"""Tracer: the commit image boots on DUT A and reports the manifest's build ID."""

import json

from hil import config


def test_commit_image_boots_and_reports_build_id(dut_a, fw_manifest, rig_config):
    image = fw_manifest.image("commit")
    result = dut_a.flash(image)
    print("flash: ok=%s verified=%s duration=%.1fs" % (result.ok, result.verified, result.duration_s))
    assert result.ok and result.verified, "flash failed:\n" + result.output_tail

    info = dut_a.wait_api(noise_psk=rig_config.dut_api_key)

    reports = config.reports_dir()
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "dut-a.json").write_text(
        json.dumps(
            {"project_version": info.project_version, "compilation_time": info.compilation_time},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    assert info.project_version == fw_manifest.build_id, "DUT reports project_version %r, manifest build_id is %r" % (
        info.project_version,
        fw_manifest.build_id,
    )
    print("build ID matches manifest: %s" % fw_manifest.build_id)
