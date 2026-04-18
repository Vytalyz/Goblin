from __future__ import annotations

from agentic_forex.goblin import (
    create_goblin_checkpoint,
    get_goblin_program_status,
    initialize_goblin_program,
    update_goblin_phase,
)


def test_goblin_init_creates_program_structure(settings):
    report = initialize_goblin_program(settings)

    paths = settings.paths()
    assert report.total_phases == 13
    assert paths.goblin_dir.exists()
    assert paths.goblin_phase_state_dir.joinpath("GOBLIN-P00.json").exists()
    assert paths.goblin_phases_dir.joinpath("GOBLIN-P00.md").exists()
    assert paths.goblin_decisions_dir.joinpath("ADR-0001-goblin-umbrella-program.md").exists()
    assert paths.goblin_contracts_dir.joinpath("truth-stack.md").exists()
    assert paths.goblin_contracts_dir.joinpath("mt5-certification.md").exists()
    assert paths.goblin_contracts_dir.joinpath("broker-reconciliation.md").exists()
    assert paths.goblin_contracts_dir.joinpath("promotion-decision-packet.md").exists()
    assert report.current_phase_id == "GOBLIN-P00"

    first_phase = next(item for item in report.phase_records if item.phase_id == "GOBLIN-P00")
    assert first_phase.build_items
    assert first_phase.checkpoint_targets
    assert first_phase.authoritative_artifacts
    assert first_phase.regenerable_artifacts


def test_goblin_status_updates_after_phase_completion(settings):
    initialize_goblin_program(settings)
    update_goblin_phase(
        settings,
        phase_id="GOBLIN-P00",
        status="completed",
        note="foundation implemented",
        acceptance_updates={"tests_passed": 1},
    )

    report = get_goblin_program_status(settings)

    assert report.phase_counts["completed"] >= 1
    assert "GOBLIN-P01" in report.ready_phase_ids
    phase = next(item for item in report.phase_records if item.phase_id == "GOBLIN-P00")
    assert phase.acceptance_result["tests_passed"] == 1


def test_goblin_checkpoint_updates_phase_record(settings):
    initialize_goblin_program(settings)
    checkpoint = create_goblin_checkpoint(
        settings,
        phase_id="GOBLIN-P00",
        checkpoint_id="init-checkpoint",
        summary="Initialized Goblin scaffolding.",
        authoritative_artifacts=["Goblin/PROGRAM.md"],
        regenerable_artifacts=["Goblin/STATUS.md"],
        status="verification_pending",
    )

    report = get_goblin_program_status(settings)
    record = next(item for item in report.phase_records if item.phase_id == "GOBLIN-P00")

    assert checkpoint.checkpoint_path.exists()
    assert record.last_checkpoint is not None
    assert record.status == "verification_pending"


def test_goblin_init_generates_all_expected_phase_artifacts(settings):
    report = initialize_goblin_program(settings)

    for record in report.phase_records:
        for artifact in record.expected_artifacts:
            assert settings.project_root.joinpath(artifact).exists(), artifact
