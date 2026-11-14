
"""Main entry point for SafeReport."""

from pathlib import Path

import io_manager
import ai_manager
import logic_manager
import data_manager

MAX_CLARIFICATION_ATTEMPTS = 5 # max clarification reassessments per workflow (if the user keeps giving info and groq keeps returning NEEDS_CLARIFICATION)

class SafeReportApplication:
    #coordinate application workflows through supplied managers

    def __init__(
        self,
        io_manager,
        ai_manager,
        logic_manager,
        data_manager,
    ):
        self._io = io_manager
        self._ai = ai_manager
        self._logic = logic_manager
        self._data = data_manager

    def handle_ai_failure(self, reference_id, error_code):
        #save an AI failure and inform the user

        ai_result = self._ai.make_result(
            reference_id, error=error_code
        )
        assessment = self._logic.determine_report_status(ai_result)

        saved = self._data.save_report(
            reference_id, ai_result, assessment
        )

        if not saved:
            self._io.display_processing_error("SAVE_FAILED")
            return

        self._io.display_processing_error(error_code)

    def assess_report(self, reference_id, report):
        #assess a saved report using the supplied managers

        try:
            client = self._ai.get_client()
        except RuntimeError:
            self.handle_ai_failure(reference_id, "CONFIG_MISSING")
            return

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

        try:
            ai_fields = self._ai.analyze_incident(
                client, incident_data, photo_paths
            )
        except RuntimeError:
            self.handle_ai_failure(reference_id, "AI_FAILED")
            return

        ai_result = self._ai.make_result(
            reference_id, fields=ai_fields
        )

        assessment = self._logic.determine_report_status(ai_result)

        if assessment["status"] == "AI_FAILED":
            self.handle_ai_failure(reference_id, "INVALID_SCHEMA")
            return

        saved = self._data.save_report(
            reference_id, ai_result, assessment
        )

        if not saved:
            self._io.display_processing_error("SAVE_FAILED")
            return

        self._io.display_assessment_result(assessment)
        return assessment

    def run_clarification_loop(self, reference_id, report, assessment):
        #collect corrections and reassess within the configured limit

        for _ in range(MAX_CLARIFICATION_ATTEMPTS):
            if assessment["status"] not in (
                "INCOMPLETE",
                "NEEDS_CLARIFICATION",
            ):
                return

            if not assessment.get("clarification_codes"):
                return

            report["assessment"] = assessment

            try:
                changes = self._io.collect_clarifications(report)
            except (EOFError, KeyboardInterrupt):
                return

            if not changes:
                return

            if not self._data.save_clarifications(reference_id, changes):
                self._io.display_processing_error("SAVE_FAILED")
                return

            report["case_details"].update(changes)

            assessment = self.assess_report(reference_id, report)

            if assessment is None:
                return

        if assessment["status"] in (
            "INCOMPLETE",
            "NEEDS_CLARIFICATION",
        ):
            self._io.display_clarification_questions(
                assessment.get("clarification_codes", [])
            )

    def process_new_report(self):
        #collect, save and assess one new report
        report = self._io.collect_report()

        if report is None:
            return

        report = self._io.review_report_before_submission(report)

        if report is None:
            return

        try:
            report_path = self._data.create_report(report)
        except OSError:
            self._io.display_processing_error("SAVE_FAILED")
            return

        reference_id = Path(report_path).stem
        self._io.display_report_reference(reference_id)

        assessment = self.assess_report(reference_id, report)

        if assessment is not None:
            self.run_clarification_loop(
                reference_id, report, assessment
            )


def handle_ai_failure(reference_id, error_code):
    #bridges existing workflows to the application during migration

    application = SafeReportApplication(
        io_manager=io_manager,
        ai_manager=ai_manager,
        logic_manager=logic_manager,
        data_manager=data_manager,
    )
    return application.handle_ai_failure(reference_id, error_code)


def process_new_report():
    #bridge existing workflows to the application during migration
    application = SafeReportApplication(
        io_manager=io_manager,
        ai_manager=ai_manager,
        logic_manager=logic_manager,
        data_manager=data_manager,
    )
    return application.process_new_report()


def assess_report(reference_id, report):
    #bridge existing workflows to the application during migration
    application = SafeReportApplication(
        io_manager=io_manager,
        ai_manager=ai_manager,
        logic_manager=logic_manager,
        data_manager=data_manager,
    )
    return application.assess_report(reference_id, report)


def run_clarification_loop(reference_id, report, assessment):
    #bridge existing workflows to the application during migration

    application = SafeReportApplication(
        io_manager=io_manager,
        ai_manager=ai_manager,
        logic_manager=logic_manager,
        data_manager=data_manager,
    )
    return application.run_clarification_loop(
        reference_id, report, assessment
    )


def retry_failed_report():
    #Let the user retry one failed report without creating a duplicate
    reports = data_manager.get_failed_ai_reports()
    if reports is None:
        io_manager.display_processing_error("LOAD_FAILED")
        return
    report = io_manager.select_saved_report(reports)
    if report is not None:
        reference_id = report["reference_id"]

        assessment = assess_report(reference_id, report)

        if assessment is not None:
            run_clarification_loop(
                reference_id, report, assessment
            )

def clarify_report():
    #resume clarification for a saved report

    reports = data_manager.load_reports()

    if reports is None:
        io_manager.display_processing_error("LOAD_FAILED")
        return

    #retrieve reports that require clarification
    reports = [
        report for report in reports
        if isinstance(report.get("assessment"), dict)
        and report["assessment"].get("status")
        in ("INCOMPLETE", "NEEDS_CLARIFICATION")
    ]

    report = io_manager.select_saved_report(reports)

    if report is None:
        return

    #resume using the existing reference ID and assessment
    run_clarification_loop(
        report["reference_id"],
        report,
        report["assessment"]
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

        if choice == "1":
            process_new_report()
        elif choice == "2":
            retry_failed_report()
        elif choice == "3":
            clarify_report()


if __name__ == "__main__":
    run()
