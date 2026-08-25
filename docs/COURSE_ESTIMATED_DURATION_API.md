# Course-Level Estimated Duration

Every endpoint that returns a course object now includes two new **read-only, computed** fields —
`estimated_total_minutes` and `estimated_duration`. There's nothing to send when creating/updating
a course; these are derived automatically from the sum of each curriculum item's
[`estimated_minutes`](./CURRICULUM_ITEM_ESTIMATED_TIME_API.md), recomputed live on every request
(not cached, so it's always accurate as items are added/edited/removed).

## Fields

| Field | Type | Notes |
|---|---|---|
| `estimated_total_minutes` | int \| null | Sum of `estimated_minutes` across every non-deleted item in every non-deleted section of the course. `null` if **no** item in the course has an estimate set (not `0`). |
| `estimated_duration` | string \| null | Human-friendly rendering of `estimated_total_minutes`, auto-scaled to the largest sensible unit. `null` under the same condition as above. |

### Auto-scaling rule

`estimated_duration` steps up a unit once the total crosses a threshold, and shows up to two units
for readability:

| Total | Rendered as |
|---|---|
| < 60 minutes | `"45 mins"` (or `"1 min"` for exactly 1) |
| ≥ 60 minutes, < 24 hours | `"2 hrs 15 mins"` (minutes part omitted if it's exactly on the hour, e.g. `"1 hr"`) |
| ≥ 24 hours, < 7 days | `"3 days 4 hrs"` (hours part omitted if exactly on the day, e.g. `"2 days"`) |
| ≥ 7 days | `"1 week 2 days"` (days part omitted if exactly on the week, e.g. `"2 weeks"`) |

Worked examples: `61 → "1 hr 1 min"`, `1500 → "1 day 1 hr"`, `10440 → "1 week"` (10440 min = 7
days 6 hrs, but 6 hrs rounds off the "days" tier since the **weeks** tier only shows a days
remainder, not hours — see note below).

> **Note on precision**: once the total is large enough to show in weeks, only a whole-days
> remainder is shown (hours are dropped); once it's shown in days, only a whole-hours remainder is
> shown (minutes are dropped). This keeps the string short and readable for long courses — it's a
> display estimate, not a stopwatch.

## Where it appears

Anywhere a `CourseReadDTO`/`PublicCourseReadDTO` (or anything built on top of them —
`CourseManageDetailDTO`, `PublicCourseDetailDTO`, `EnrolledCourseDTO`) is returned, which is
effectively every course-returning endpoint:

- `GET /courses` (public list)
- `GET /courses/featured`, `GET /courses/recent`
- `GET /courses/enrolled`, `GET /courses/bookmarked`
- `GET /courses/manage` (management list)
- `GET /courses/manage/{id}` (management detail)
- `GET /courses/{slug}` (public detail)
- `POST /courses`, `PATCH /courses/{id}`, `PATCH /courses/{id}/publish` (create/update responses)

## Example

```json
{
  "id": "course-uuid",
  "title": "Intro to Trauma-Informed Care",
  "...": "...other course fields...",
  "estimated_total_minutes": 130,
  "estimated_duration": "2 hrs 10 mins",
  "instructors": [ "..." ]
}
```

A brand-new course (or one where every item's `estimated_minutes` is unset) returns both fields
absent from the JSON entirely, per this API's standard null-stripping behavior — treat that the
same as "no estimate available," and just don't render a duration badge for it.

## Nothing to configure directly

There is no course-level "set the duration" endpoint — it's purely derived. To change it, set/edit
`estimated_minutes` on the course's individual curriculum items (see
[`CURRICULUM_ITEM_ESTIMATED_TIME_API.md`](./CURRICULUM_ITEM_ESTIMATED_TIME_API.md)); the course
total updates automatically on the next read.
