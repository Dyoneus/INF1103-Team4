# SafeReport — Workplace Safety Report Readiness Checker

**Module:** INF1103  
**Lab Group:** P6  
**Group:** 4  
**Repository:** [INF1103-Team4](https://github.com/Dyoneus/INF1103-Team4)

---

## 1. Problem Statement and Target Users

### What real-world problem does the application aim to solve?

Workplace safety concerns are often described in forms. If the description is vague or leaves out important details such as **what was observed** or **where it happened**, the report can be harder to follow up.

The Ministry of Manpower (MOM) has stated that some SnapSAFE reports did not contain sufficient information for follow-up, showing that report completeness is a real issue.

**SafeReport** aims to help users check whether a workplace safety description contains enough useful information for review and identify any details that need clarification.

### Target users

- Workers or members of the public
- Workplace safety personnel who review safety feedback

---

## 2. User Inputs — `io_manager.py`

### What information or data will users provide?

The main input is a **free-text description** of what the user observed.

Users do not need to manually fill in separate fields for the safety category, location, date, or time.

### User Input Fields

- Description
- Date
- Time
- Location

### Example Input

> “Yesterday afternoon I saw two workers standing near the open edge of the third floor behind Block 30. I couldn’t see any barrier around them.”

### Basic Input Validation

- Reject empty descriptions
- Re-prompt the user when input is invalid

---

## 3. Use of AI — `ai_manager.py`

### How will AI be used?

AI is used to check the user’s free-text description and convert it into fixed structured fields.

| AI Field | Values | Purpose |
|---|---|---|
| **Issue Clarity** | `CLEAR` / `UNCLEAR` | Whether the observed safety concern can be understood |
| **Location Quality** | `ADEQUATE` / `VAGUE` / `MISSING` | How usable the stated location is for follow-up |
| **Date Quality** | `EXACT` / `APPROXIMATE` / `MISSING` | Whether useful date information is present |
| **Time Quality** | `EXACT` / `APPROXIMATE` / `MISSING` | Whether useful time information is present |
| **Safety Category** | Fixed category list | General type of safety concern described |

### What output will the AI generate?

The AI will analyse the user’s free-text safety observation and return a **structured JSON response** containing fixed fields such as:

- Date quality
- Time quality
- Location quality
- Issue clarity
- Safety category

These fields use predefined values such as `CLEAR`, `VAGUE`, `MISSING`, or `APPROXIMATE`.

The AI will only **extract and organise the information**.

---

## 4. Business Rules — `logic_manager.py`

The Logic Manager applies rules to the AI-generated fields and determines the final report status.

### `INCOMPLETE`

**Condition:**

- The safety issue is unclear, **OR**
- The location is unidentified

**Outcome:**

- Set the report status to `INCOMPLETE`

---

### `NEEDS_CLARIFICATION`

**Condition:**

- The issue is clear, but the location is vague, **OR**
- Date/time information is missing

**Outcome:**

- Set the report status to `NEEDS_CLARIFICATION`

---

### `READY_FOR_REVIEW`

**Condition:**

- The issue is clear, **AND**
- The location is adequate, **AND**
- Usable date and time information are present

**Outcome:**

- Set the report status to `READY_FOR_REVIEW`

---

### `AI_FAILED`

**Condition:**

- The AI output is invalid, **OR**
- The API fails

**Outcome:**

- Set the report status to `AI_FAILED`
- Allow the record to be retried later

---


## Repository

🔗 https://github.com/Dyoneus/INF1103-Team4
