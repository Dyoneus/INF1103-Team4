
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

    # save the original report
    try:
        report_path = data_manager.create_report(report)
    except OSError:
        io_manager.display_processing_error("SAVE_FAILED")
        return

    reference_id = Path(report_path).stem
    io_manager.display_report_reference(reference_id)

    # initialise the AI client
    try:
        client = ai_manager.get_client()
    except RuntimeError:
        handle_ai_failure(reference_id, "CONFIG_MISSING")
        return

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

    io_manager.display_clarification_questions(
        assessment["clarification_codes"]
    )


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

        process_new_report()


if __name__ == "__main__":
    run()
