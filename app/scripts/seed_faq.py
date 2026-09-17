"""Seeds the Help Centre FAQ library (categories + items) from the SWCL FAQ
Content Library v1.0 (40 articles: 24 Student, 12 Instructor, 4 Both).

`FAQItem` has dedicated `audience`, `keywords`, `escalation_route` and
`related_article_ids` columns, so each article's fields map directly onto the
schema. `answer` combines the source doc's quick answer and full answer.
Category names are still suffixed with their audience (e.g. "Live Sessions
(Instructor)") because the source doc reuses the same category name across
audiences and category rows aren't otherwise split by audience.

`related_article_ids` references other articles by their FAQ ID (e.g.
"STU-002"), so items are seeded in two passes: first create/update every item
to learn its DB id, then resolve each article's related FAQ IDs into UUIDs.

Idempotent: re-running updates existing rows (matched by category name, then
by question within that category) instead of duplicating them.

Usage:
    python -m app.scripts.seed_faq
"""

import asyncio

from sqlalchemy import select

import app.models  # noqa: F401 - registers every entity on Base.metadata before use
from app.core.database import AsyncSessionLocal
from app.modules.support.entity import FAQAudienceEnum, FAQCategory, FAQItem

AUDIENCE_MAP = {
    "Student": FAQAudienceEnum.STUDENT,
    "Instructor": FAQAudienceEnum.INSTRUCTOR,
    "Both": FAQAudienceEnum.BOTH,
}

# Each tuple: (id, audience, category, escalation_route, question, quick_answer,
# full_answer, keywords, related_ids)
FAQ_ARTICLES: list[tuple[str, str, str, str, str, str, str, str, str]] = [
    ("STU-001", "Student", "Getting Started", "Course Access / Enrolment",
     "How do I enrol in a course?",
     "Open the Course Catalogue, choose a course and select Enrol or Purchase, depending on the course.",
     "From the left menu, go to the Course Catalogue. Open the course you want to take and review the "
     "course description, duration, price and access conditions. Select Enrol for a free or "
     "already-funded course, or Purchase for a paid course. Complete any required payment or "
     "registration steps. Once enrolment is successful, the course will appear under My Courses.",
     "enrol, enrollment, register, join course, purchase course", "STU-002, STU-003, STU-019"),
    ("STU-002", "Student", "Getting Started", "Course Access",
     "Where can I find the courses I am enrolled in?",
     "All courses linked to your account appear in My Courses.",
     "Select My Courses from the left menu. You can filter your courses by In Progress, Not Started, "
     "Completed, or Saved. Select a course card to open it. If a course you paid for or were assigned "
     "to doesn't appear, refresh the page and make sure you're signed in to the correct account.",
     "my courses, enrolled courses, missing course, course list", "STU-001, STU-003, GEN-001"),
    ("STU-003", "Student", "Courses and Learning", "Course Access",
     "How do I continue a course I already started?",
     "Use Continue Learning on the dashboard or open the course from My Courses.",
     "From the Dashboard, select Continue Learning to resume your most recently active course. The "
     "platform should return you to the most recent incomplete lesson or activity. Alternatively, open "
     "My Courses, select the course, then select Continue. Your progress should be saved automatically "
     "as you complete required activities.",
     "continue course, resume learning, continue learning, last lesson", "STU-004, STU-005"),
    ("STU-004", "Student", "Learning Progress", "Learning Progress",
     "How is my course progress calculated?",
     "Progress is based on required course activities that you have completed.",
     "Course progress is calculated based on the required activities configured for that course, such "
     "as lessons, videos, quizzes, assignments, or attendance requirements. Optional resources normally "
     "don't reduce your progress unless they're configured as required. A course is marked as Completed "
     "only when you meet all completion requirements.",
     "progress, completion percentage, course completion, required activities", "STU-005, STU-009, STU-012"),
    ("STU-005", "Student", "Learning Progress", "Learning Progress",
     "Why has my course progress not updated?",
     "A progress delay can occur if an activity was not fully completed, a result is pending, or your "
     "connection did not synchronise.",
     "First, reopen the course and check the activity that should have updated your progress. Make sure "
     "the lesson, quiz, or assignment is marked as completed. If an assessment is awaiting marking, your "
     "course may not reach full completion until the result is published. If you were studying with an "
     "unstable connection, refresh the page after reconnecting. If the progress remains incorrect, "
     "contact support and include the course name and the affected activity.",
     "progress not updating, completion stuck, sync, activity incomplete", "STU-004, STU-010, GEN-003"),
    ("STU-006", "Student", "Courses and Learning", "Course Access",
     "What happens when my course access expires?",
     "You may lose access to course content after the expiry date, but completed records should remain "
     "in your account.",
     "The course page will display an access expiry date. After expiry, you may no longer be able to "
     "access course lessons or assessments. Your completed learning history, results and certificates "
     "should remain available where applicable. If you need more time because of an approved arrangement "
     "or a technical issue, contact support before the expiry date, if possible.",
     "course expiry, access expires, expired course, extension", "STU-002, STU-012, STU-019"),
    ("STU-007", "Student", "Assessments", "Assessments",
     "How do I start an assessment?",
     "Open Assessments, select the assessment and choose Start.",
     "Select Assessments from the left menu. Locate the required assessment under Upcoming or Not "
     "Started. Review the instructions, pass mark, time limit and number of attempts before selecting "
     "Start. Do not start a timed assessment until you are ready to complete it.",
     "start assessment, quiz, assignment, test", "STU-008, STU-009, STU-010"),
    ("STU-008", "Student", "Assessments", "Assessments",
     "What is the pass mark for an assessment?",
     "The pass mark is shown on the assessment page and may differ between courses.",
     "Open the assessment details to view the required pass mark. Different courses or assessment types "
     "may have different thresholds. The pass mark shown applies to that assessment. If an assessment is "
     "manually marked, your final result may remain pending until the instructor completes the review.",
     "pass mark, passing score, assessment score", "STU-007, STU-009, STU-011"),
    ("STU-009", "Student", "Assessments", "Assessments",
     "Can I retake an assessment if I do not pass?",
     "A retake is available only where the course rules allow it.",
     "After a failed assessment, check the result page. If another attempt is permitted, the page will "
     "show Retake Available and any waiting period or conditions. Some assessments may limit the number "
     "of attempts or require tutor review before a further attempt. If you believe you should be able to "
     "retake but no option is shown, contact support or your instructor.",
     "retake, failed assessment, retry quiz, attempts", "STU-008, STU-011"),
    ("STU-010", "Student", "Assessments", "Assessment Technical Issue",
     "Why can I not submit my assessment?",
     "Check required questions, file requirements, time limits and your internet connection.",
     "Before submitting, ensure you have answered all required questions and attached any mandatory "
     "files in the correct format and size. If the Submit button is unavailable, review the assessment "
     "instructions to identify any incomplete fields. If the page freezes or your connection drops, "
     "avoid repeatedly pressing Submit. Reconnect, reload carefully, and check whether the submission "
     "was recorded. Contact support if the problem persists.",
     "cannot submit, submit assessment, upload error, assessment technical issue", "STU-007, GEN-003"),
    ("STU-011", "Student", "Results and Feedback", "Assessment Results",
     "Where can I see my assessment results and tutor feedback?",
     "Open Assessments and select Results or the completed assessment.",
     "Go to Assessments and open Results or Completed. Select the assessment to view the score, result, "
     "attempt information, and any feedback released by the instructor. If the status is Submitted or "
     "Awaiting Marking, the result has not yet been published.",
     "results, feedback, score, tutor comments, marking", "STU-008, STU-009"),
    ("STU-012", "Student", "Certificates", "Certificate Issue",
     "When will my certificate become available?",
     "A certificate becomes available once all configured course-completion requirements are met.",
     "Your certificate will normally be generated once you complete all required activities and pass all "
     "required assessments. Some courses may also require attendance or an instructor-approved activity. "
     "Once the course status changes to Completed, check Certificates. If the course is complete but no "
     "certificate appears, contact support.",
     "certificate available, course complete, pending certificate", "STU-013, STU-014, STU-015"),
    ("STU-013", "Student", "Certificates", "Certificate Issue",
     "How do I download my certificate?",
     "Open Certificates, find the completed course and select Download Certificate.",
     "Select Certificates from the left menu. Find the certificate you want, then select Download "
     "Certificate. The certificate should open or download as a PDF. Save the file to your device. If "
     "the download fails, try again after checking your internet connection and browser download "
     "settings.",
     "download certificate, pdf certificate, certificate file", "STU-012, STU-014, GEN-003"),
    ("STU-014", "Student", "Certificates", "Certificate Verification",
     "How can an employer or organisation verify my certificate?",
     "Use the certificate verification code or verification link shown on the certificate.",
     "Each eligible SWCL certificate should include a unique certificate ID or verification code. An "
     "employer or organisation can use the SWCL certificate verification page to enter the code and "
     "confirm the certificate's validity. Verification should reveal only the information necessary to "
     "confirm authenticity.",
     "verify certificate, certificate id, employer verification, authenticity", "STU-013, STU-015"),
    ("STU-015", "Student", "Certificates", "Certificate Correction",
     "What should I do if my name is incorrect on my certificate?",
     "Correct your profile name and contact support before using or sharing the certificate.",
     "First, check the name recorded in Profile Settings. If your profile name is incorrect, update it "
     "where the platform allows. Then contact support and select Certificate Issue, explaining which "
     "certificate needs correction. Do not edit the certificate file yourself. A corrected certificate "
     "should retain an audit record and may receive an updated version or status.",
     "wrong name certificate, certificate correction, name error", "STU-013, GEN-002"),
    ("STU-016", "Student", "CPD Record", "CPD Record",
     "What does CPD mean and what can I record?",
     "CPD means Continuing Professional Development and can include relevant learning activities "
     "completed on or outside SWCL.",
     "Your CPD Record helps you maintain evidence of professional learning. Depending on platform "
     "settings, you may record SWCL courses, webinars, workshops, conferences, supervision, professional "
     "reading and other relevant learning activities. Each entry should include the date, activity, "
     "learning hours and what you learned. External activities may require supporting evidence, such as "
     "a certificate or attendance record.",
     "cpd, continuing professional development, learning hours, professional learning", "STU-017, STU-018"),
    ("STU-017", "Student", "CPD Record", "CPD Record",
     "How are SWCL course hours added to my CPD record?",
     "Eligible SWCL learning can be added automatically when completion is confirmed.",
     "When an SWCL course or qualifying live session is configured for CPD, the platform can add the "
     "approved learning hours to your CPD Record upon completion. Check the entry for the course title, "
     "completion date and hours. If the course is complete but the CPD entry is missing, contact "
     "support.",
     "automatic cpd, cpd hours, course hours, webinar hours", "STU-016, STU-018"),
    ("STU-018", "Student", "CPD Record", "CPD Record",
     "Can I add learning completed outside SWCL to my CPD record?",
     "Yes, where enabled, you can add an external CPD activity manually and attach evidence.",
     "Open the CPD Record and select Add CPD Entry. Choose the activity type, add the title, date, "
     "learning hours, and a short description of what you learned. Upload supporting evidence if "
     "available. External activities may appear as self-recorded or unverified unless reviewed through "
     "an organisational process.",
     "external cpd, add cpd, manual cpd, upload evidence", "STU-016, STU-017"),
    ("STU-019", "Student", "Payments and Billing", "Payment and Billing",
     "What payment methods are accepted?",
     "Available payment methods are shown at checkout and may vary by country, currency or product.",
     "When purchasing a course or subscription, the checkout page will show the payment methods "
     "currently supported by SWCL. Select an available method and follow the secure payment "
     "instructions. Do not send card or banking details via support messages or in community "
     "discussions.",
     "payment methods, card, pay, checkout, billing", "STU-020, STU-021"),
    ("STU-020", "Student", "Payments and Billing", "Payment Issue",
     "Why did my payment fail?",
     "Payments can fail because of bank declines, incorrect details, connection problems or "
     "payment-provider errors.",
     "Check that your payment details are correct and that your bank or payment provider has not "
     "blocked the transaction. If the page appears to fail after you have confirmed payment, check "
     "Payment and Billing before trying again to avoid a duplicate charge. If money has left your "
     "account but the course is still locked, contact support with only the transaction reference; do "
     "not send full card details.",
     "payment failed, card declined, transaction failed, duplicate payment", "STU-019, STU-021"),
    ("STU-021", "Student", "Payments and Billing", "Payment and Billing",
     "Where can I find my receipt or payment history?",
     "Open Payment and Billing to view transactions, invoices and available receipts.",
     "Select Payment and Billing from your account menu. The page should display your payment history, "
     "transaction status and any invoices or receipts available to download. If a completed payment is "
     "missing, allow for normal processing time, then contact support with the date, amount and "
     "transaction reference.",
     "receipt, invoice, payment history, transaction", "STU-019, STU-020"),
    ("STU-022", "Student", "Live Sessions", "Live Session Support",
     "How do I register for and join a live session?",
     "Open Live Sessions, choose a session, register, then use the Join button when the session becomes "
     "available.",
     "Go to Live Sessions and select the session you want to attend. Review the date, time and time "
     "zone, then select Register. Your registration should appear under Your Registrations. Before the "
     "session, return to Live Sessions and select Join when the join link becomes active. You may also "
     "receive a reminder if notifications are enabled.",
     "live session, webinar, register, join session, zoom, teams", "STU-023, GEN-004"),
    ("STU-023", "Student", "Live Sessions", "Live Session Support",
     "What happens if I miss a live session?",
     "Check whether a recording or alternative activity is available.",
     "Open Live Sessions and look under Past Sessions or Recordings. Some sessions may offer a "
     "recording, slides or follow-up resources. If attendance is mandatory for course completion, the "
     "course instructions should state whether an alternative session or activity is available. If you "
     "are unsure, contact your instructor or support.",
     "missed webinar, missed live session, recording, attendance", "STU-022"),
    ("STU-024", "Student", "Resources", "Resource Access",
     "How do I download learning resources and find low-data options?",
     "Open Resources and use the download, file-size and low-data filters.",
     "Select Resources from the menu. Search or filter by topic, format, or low-data availability. "
     "Downloadable items should display the file type and size before downloading. Where available, use "
     "transcripts, audio-only files, or low-data resources if you have limited connectivity. Saved items "
     "should remain available under your saved resources.",
     "resources, download, low data, transcript, audio, file size", "GEN-003"),
    ("INS-001", "Instructor", "Assigned Courses", "Instructor Access",
     "Where can I see the courses assigned to me?",
     "Open My Courses from the instructor dashboard to see your current teaching assignments.",
     "Your instructor dashboard should display Assigned or Active Courses. Open My Courses to view each "
     "course, your role, active cohorts, learner numbers, and relevant course dates. If an expected "
     "course is missing, contact the course administrator, as your current assignment and permissions "
     "control access.",
     "assigned courses, instructor courses, teaching assignment, missing course", "INS-002, INS-003"),
    ("INS-002", "Instructor", "Learners and Cohorts", "Learner Management",
     "How do I view learners and their progress?",
     "Open a course or cohort and select Learners or Progress Overview.",
     "In My Courses, open the relevant course and cohort. Select Learners or Progress Overview to view "
     "authorised learners, progress, last activity, assessment status and relevant support flags. Use "
     "filters to identify learners who are inactive, behind schedule or awaiting feedback. Only data for "
     "your assigned courses and cohorts should be visible.",
     "learner progress, cohort, instructor learners, inactive learner", "INS-001, INS-003"),
    ("INS-003", "Instructor", "Learners and Cohorts", "Learner Support",
     "How do I identify learners who may need additional support?",
     "Use engagement and progress indicators as prompts, then review the learner context before taking "
     "action.",
     "The dashboard may flag learners using configurable indicators such as prolonged inactivity, "
     "repeated difficulty with assessments, overdue required work, or an open support issue. These flags "
     "are prompts, not automatic judgements. Review the learner record and course context before "
     "contacting the learner or escalating a concern. Record only relevant teaching or support "
     "information.",
     "at risk learner, inactive learner, support flag, engagement", "INS-002, INS-007"),
    ("INS-004", "Instructor", "Assessments and Marking", "Marking Support",
     "How do I mark an assessment?",
     "Open the Marking Queue, select a submission, apply the configured rubric or score and add "
     "feedback.",
     "Go to the Marking Queue and open the submitted assessment. Review the learner's submission against "
     "the assessment instructions and marking criteria. Record the mark or rubric outcome and provide "
     "clear, constructive feedback. Save as a Draft if you are not ready to release it. If moderation is "
     "required, submit the marked work to the moderation workflow. Otherwise, confirm Publish or Return "
     "to Learner when ready.",
     "mark assessment, marking queue, rubric, grade, feedback", "INS-005, INS-006"),
    ("INS-005", "Instructor", "Assessments and Marking", "Marking Support",
     "Can I save assessment feedback as a draft before the learner sees it?",
     "Yes. Draft feedback should remain private until you explicitly publish or return the result.",
     "While marking, use Save Draft to preserve your work without releasing it to the learner. Draft "
     "status should be clearly indicated. Reopen the submission later to continue marking. The learner "
     "should see only the final mark and feedback after the authorised publication action.",
     "draft feedback, save marking, unpublished result", "INS-004, INS-006"),
    ("INS-006", "Instructor", "Moderation", "Moderation Support",
     "What happens when an assessment requires moderation?",
     "The marked submission is routed to an authorised moderator before the final result is released.",
     "Complete the initial marking and feedback, then submit the work for moderation. The moderator "
     "reviews the submission, mark and feedback, and may confirm, amend, return or escalate the "
     "decision. If a result changes, record the reason. Do not release a moderation-required result to "
     "the learner until the required sign-off is complete.",
     "moderation, second marking, moderator, assessment review", "INS-004, INS-005"),
    ("INS-007", "Instructor", "Learner Questions and Communication", "Instructor Communication",
     "Where can I see and respond to learner questions?",
     "Open Learner Questions, Messages, or course Discussions from the instructor dashboard.",
     "The dashboard should display unread learner questions and messages. Open the relevant thread to "
     "review the course context, respond, assign or escalate the item, and mark it as resolved where "
     "appropriate. If the same question is asked repeatedly, consider creating a course announcement or "
     "proposing an FAQ article.",
     "learner question, message, discussion, respond to learner", "INS-003, INS-008"),
    ("INS-008", "Instructor", "Announcements", "Instructor Communication",
     "How do I send an announcement to a course or cohort?",
     "Create an announcement, choose the authorised audience, then publish immediately or schedule it.",
     "Open Announcements from the instructor dashboard or course workspace. Select Create Announcement, "
     "enter a clear title and message, choose the course or cohort audience, set the priority, and "
     "optionally schedule the publication time. Review the audience carefully before publishing. Editing "
     "a published announcement should not generate duplicate notifications unless a new notification is "
     "intentionally sent.",
     "announcement, cohort message, course update, instructor communication", "INS-007, INS-009"),
    ("INS-009", "Instructor", "Live Sessions", "Live Session Support",
     "How do I create or manage a live session?",
     "Open Live Sessions, create the session details, add the joining link and select the relevant "
     "course or cohort.",
     "Create a live session with a title, course or cohort, date, time, time zone, duration, capacity "
     "and meeting link. Add any preparation resources and configure learner reminders. After the "
     "session, record attendance and upload approved follow-up materials or recordings, where "
     "applicable. If you cancel or reschedule, affected learners should receive an update.",
     "create live session, webinar, attendance, meeting link, instructor", "INS-008, INS-010"),
    ("INS-010", "Instructor", "Course Content", "Course Content / QA",
     "How do I report outdated or incorrect course content?",
     "Use the content action or report issue function rather than editing published content without "
     "approval.",
     "Open the affected course content and select Report Issue or Request Update where available. "
     "Describe what is outdated, incorrect, inaccessible or broken, and identify the affected lesson or "
     "resource. The request should enter the content or quality workflow with an owner, priority and "
     "status. Published content changes may require approval and version control.",
     "outdated content, broken link, content error, request update", "INS-009, INS-011"),
    ("INS-011", "Instructor", "Quality Assurance", "Quality Assurance",
     "How do I view course performance and learner feedback?",
     "Open Course Analytics or Quality to review completion, assessment, engagement and feedback "
     "trends.",
     "Course Analytics should show measures such as completion rate, learner activity, assessment "
     "performance, support demand and learner feedback. Use filters for cohort and reporting period. "
     "Treat metrics as indicators that require context; low completion may relate to course design, "
     "assessment difficulty, learner circumstances or technical barriers. Add an improvement action "
     "where a pattern requires follow-up.",
     "course analytics, learner feedback, completion rate, quality assurance", "INS-010, INS-012"),
    ("INS-012", "Instructor", "Technical Support", "Technical Support",
     "What should I do if marking, feedback or course content will not save?",
     "Keep the page open where possible, check your connection and retry once before escalating.",
     "If the platform reports a save error, do not repeatedly publish or submit the same action. Check "
     "your internet connection and whether you've already saved a draft. If organisational policy "
     "permits, copy any unsaved long-form feedback to a secure temporary location, then retry. If the "
     "issue persists, raise a technical support ticket for the affected course, assessment or content "
     "item, including the approximate time of the error. Do not include unnecessary learner data in the "
     "ticket.",
     "save error, marking not saving, feedback error, technical issue instructor", "INS-004, GEN-003"),
    ("GEN-001", "Both", "Account and Login", "Account Access",
     "I cannot log in. What should I do?",
     "Check your email address and password, then use the password reset option if needed.",
     "Ensure you are signing in with the email address linked to your SWCL account. Check for typos and "
     "make sure Caps Lock isn't affecting your password. If you have forgotten your password, select "
     "Forgot Password and follow the reset instructions sent to your email. If you do not receive the "
     "message, check your spam or junk folder. Contact support if you still can't access your account.",
     "login, sign in, cannot log in, forgot password, reset password", "GEN-002, GEN-003"),
    ("GEN-002", "Both", "Account and Profile", "Account / Profile",
     "How do I update my profile information?",
     "Open Profile Settings and edit the fields your account allows you to change.",
     "Go to Profile Settings to update personal or professional information, learning preferences and "
     "other editable account details. Some identity fields may be restricted if they are linked to "
     "certificates, institutional records or verification. If you cannot change an incorrect field, "
     "contact support rather than creating a second account.",
     "profile, change name, email, professional details, account settings", "GEN-001, STU-015"),
    ("GEN-003", "Both", "Technical Support", "Technical Support",
     "What should I do if the platform is not loading or a feature is not working?",
     "Refresh the page, check your connection and browser, then contact support if the problem "
     "continues.",
     "First, check that your internet connection is stable. Refresh the page and try the action once. "
     "If possible, use a current version of a supported browser and close unnecessary tabs. For upload "
     "or video issues, check the file size and connection quality. If the problem persists, note the "
     "page, feature, time and any error message, then submit a support ticket. Avoid sending passwords "
     "or full payment card details.",
     "technical issue, page not loading, browser, error, upload, video", "GEN-001, STU-010, INS-012"),
    ("GEN-004", "Both", "Notifications", "Account / Notifications",
     "How do I change my notification preferences?",
     "Open Notifications or Account Settings and choose which non-essential updates you want to receive.",
     "Go to Notifications or Account Settings to review the available email, push or other notification "
     "options. You can usually change preferences for announcements, course updates, reminders and "
     "community activity. Essential account, security, payment or mandatory learning notices may still "
     "be sent where necessary.",
     "notifications, email alerts, push notification, reminder settings", "GEN-002"),
]


def _build_answer(quick_answer: str, full_answer: str) -> str:
    return f"{quick_answer}\n\n{full_answer}"


def _parse_keywords(keywords: str) -> list[str]:
    return [k.strip() for k in keywords.split(",") if k.strip()]


def _parse_related(related: str) -> list[str]:
    return [r.strip() for r in related.split(",") if r.strip()]


async def _get_or_create_category(session, name: str, order: int) -> FAQCategory:
    stmt = select(FAQCategory).where(FAQCategory.name == name)
    category = (await session.execute(stmt)).scalar_one_or_none()
    if category is None:
        category = FAQCategory(name=name, order=order)
        session.add(category)
    else:
        category.order = order
    await session.flush()
    return category


async def _get_or_create_item(
    session,
    category_id,
    question: str,
    answer: str,
    order: int,
    audience: FAQAudienceEnum,
    keywords: list[str],
    escalation_route: str,
) -> FAQItem:
    stmt = select(FAQItem).where(FAQItem.category_id == category_id, FAQItem.question == question)
    item = (await session.execute(stmt)).scalar_one_or_none()
    if item is None:
        item = FAQItem(
            category_id=category_id,
            question=question,
            answer=answer,
            order=order,
            is_published=True,
            audience=audience,
            keywords=keywords,
            escalation_route=escalation_route,
            related_article_ids=[],
        )
        session.add(item)
    else:
        item.answer = answer
        item.order = order
        item.is_published = True
        item.audience = audience
        item.keywords = keywords
        item.escalation_route = escalation_route
    await session.flush()
    return item


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        category_order: dict[str, int] = {}
        category_ids: dict[str, object] = {}
        item_order: dict[str, int] = {}
        items_by_faq_id: dict[str, FAQItem] = {}

        for (
            faq_id, audience, category_name, escalation, question, quick_answer, full_answer,
            keywords, related,
        ) in FAQ_ARTICLES:
            display_category = f"{category_name} ({audience})"

            if display_category not in category_order:
                category_order[display_category] = len(category_order)
                category = await _get_or_create_category(
                    session, display_category, category_order[display_category]
                )
                category_ids[display_category] = category.id
                item_order[display_category] = 0

            item = await _get_or_create_item(
                session,
                category_ids[display_category],
                question,
                _build_answer(quick_answer, full_answer),
                item_order[display_category],
                AUDIENCE_MAP[audience],
                _parse_keywords(keywords),
                escalation,
            )
            items_by_faq_id[faq_id] = item
            item_order[display_category] += 1

        # Second pass: related articles are referenced by FAQ ID, which is only
        # resolvable to a DB id once every article above has been created.
        for faq_id, *_rest, related in FAQ_ARTICLES:
            item = items_by_faq_id[faq_id]
            item.related_article_ids = [
                items_by_faq_id[related_id].id
                for related_id in _parse_related(related)
                if related_id in items_by_faq_id
            ]

        await session.commit()
        print(f"Seeded {len(category_ids)} FAQ categories and {len(items_by_faq_id)} FAQ items.")


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
