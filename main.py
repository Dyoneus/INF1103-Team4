
"""Main entry point for SafeReport."""

from pathlib import Path

import io_manager
import ai_manager
import logic_manager
import data_manager


def handle_ai_failure(reference_id, error_code):
    """Save an AI failure and inform the user."""

    ai_result = ai_manager.make_result(
        reference_id, error=error_code
    )

    assessment = logic_manager.determine_report_status(ai_result)

    saved = data_manager.save_report(
        reference_id, ai_result, assessment
    )

    if not saved:
        io_manager.display_processing_error("SAVE_FAILED")
        return

    io_manager.display_processing_error(error_code)


def process_new_report():
    """Process one safety report through the four managers."""

    # collect user input
    report = io_manager.collect_report()

    if report is None:
        return

    report = io_manager.review_report_before_submission(report)
    if report is None:
        return

    # save the original report
    try:
        report_path = data_manager.create_report(report)
    except OSError:
        io_manager.display_processing_error("SAVE_FAILED")
        return

    reference_id = Path(report_path).stem
    io_manager.display_report_reference(reference_id)

    assess_report(reference_id, report)


def assess_report(reference_id, report):
    """Assess an existing record and replace its saved AI and logic results."""
    # initialise the AI client
    try:
        client = ai_manager.get_client()
    except RuntimeError:
        handle_ai_failure(reference_id, "CONFIG_MISSING")
        return

    while True:
        # prepare incident information for the AI
        case_details = report["case_details"]

        incident_data = {
            key: value
            for key, value in case_details.items()
            if key != "photos"
        }

        if case_details.get("consent_for_image_use") is True:
            photo_paths = case_details.get("photos", [])
        else:
            photo_paths = []

        # analyse the incident
        try:
            ai_fields = ai_manager.analyze_incident(
                client, incident_data, photo_paths
            )
        except RuntimeError:
            handle_ai_failure(reference_id, "AI_FAILED")
            return

        ai_result = ai_manager.make_result(
            reference_id, fields=ai_fields
        )

        # determine report readiness
        assessment = logic_manager.determine_report_status(ai_result)

        if assessment["status"] == "AI_FAILED":
            handle_ai_failure(reference_id, "INVALID_SCHEMA")
            return

        # save AI and Logic results
        saved = data_manager.save_report(
            reference_id, ai_result, assessment
        )

        if not saved:
            io_manager.display_processing_error("SAVE_FAILED")
            return

        # display results to the user
        io_manager.display_assessment_result(assessment)
        report["assessment"] = assessment
        if not assessment["clarification_codes"]:
            return
        if not collect_and_save_clarifications(reference_id, report):
            return


def collect_and_save_clarifications(reference_id, report):
    """Collect and persist corrections before allowing another AI assessment."""
    changes = io_manager.collect_clarifications(report)
    if not changes:
        return False
    if not data_manager.save_clarifications(reference_id, changes):
        io_manager.display_processing_error("SAVE_FAILED")
        return False
    report["case_details"].update(changes)
    return True


def retry_failed_report():
    """Let the user retry one failed report without creating a duplicate."""
    reports = data_manager.get_failed_ai_reports()
    if reports is None:
        io_manager.display_processing_error("LOAD_FAILED")
        return
    report = io_manager.select_saved_report(reports)
    if report is not None:
        assess_report(report["reference_id"], report)


def clarify_report():
    """Save corrections to a selected report, then assess it again."""
    reports = data_manager.load_reports()
    if reports is None:
        io_manager.display_processing_error("LOAD_FAILED")
        return
    reports = [
        report for report in reports
        if isinstance(report.get("assessment"), dict)
        and report["assessment"].get("status")
        in ("INCOMPLETE", "NEEDS_CLARIFICATION")
    ]
    report = io_manager.select_saved_report(reports)
    if report is None:
        return
    reference_id = report["reference_id"]
    if collect_and_save_clarifications(reference_id, report):
        assess_report(reference_id, report)


def run():
    """Run the SafeReport menu."""

    if data_manager.load_reports() is None:
        io_manager.display_processing_error("LOAD_FAILED")
        return

    while True:
        io_manager.display_menu()
        choice = io_manager.get_menu_choice()

        if choice == "0":
            return

        if choice == "1":
            process_new_report()
        elif choice == "2":
            retry_failed_report()
        elif choice == "3":
            clarify_report()


if __name__ == "__main__":
    run()
