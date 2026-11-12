# JAD AI study assistant

JAD is short for Mr. Job, Mr. Anthony and Dr. Philip, the founding members of
Social Work Consultancy (SWC). JAD AI helps learners on:

- **DOCUMENT** lessons
- **SCORM** lessons
- **Practice quizzes**: a QUIZ that is not the module's final assessment. It
  coaches with hints and explanations rather than handing over answers.

It is never available on scored final assessments (403), essays or quiz groups.
Code: `app/modules/jad_ai`.

## Endpoints (learner, Bearer auth)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/jad-ai/courses/{course_id}/items/{item_id}` | `available`, `lesson_kind`, `first_name`, starter `suggestions`, saved `messages`, `max_message_chars` |
| POST | `/jad-ai/courses/{course_id}/items/{item_id}/messages` | Ask. Body `{message, question_id?, from_suggestion?}`. Streams Server-Sent Events |
| DELETE | `/jad-ai/courses/{course_id}/items/{item_id}/messages` | Start a new chat |
| POST | `/jad-ai/messages/{message_id}/feedback` | `{helpful: true \| false \| null}`. A thumbs-down retires a cached answer |

Stream events: `start {cached}`, `delta {t}` (append), `replace {t}` (swap the
whole answer), `done {message_id, suggestions, cached}`, `error {message}`.
Errors before streaming come back as normal JSON: 403/404 (no access), 429 (usage
limit), 503 (not configured).

## How it saves tokens and database work

- **Lesson text is read once.** The PDF/DOCX/SCORM launch page is parsed on first
  use (in the background when the panel first loads) and stored in
  `jad_item_contexts`. It is read again only after a re-upload.
- **Semantic answer cache** (`jad_cache_entries`). Stand-alone questions (the
  first in a chat, or a tapped suggestion) are matched against earlier answers
  for the same lesson version: by exact wording via Redis, then in Postgres, then
  by meaning using embeddings. Matches are guarded so "X" never matches "not X"
  and "step 2" never matches "step 3". Embeddings use OpenAI
  (`JAD_AI_EMBEDDING_MODEL`, 256 dimensions) when `OPENAI_API_KEY` is set, and a
  built-in lexical embedding otherwise. Any change to the lesson, the quiz
  question or the prompt (`PROMPT_VERSION`) starts a fresh cache.
- **DeepSeek prefix caching.** Short lessons are sent whole, with the system
  prompt kept identical between questions, so DeepSeek bills the repeated prefix
  at its cached rate. Long lessons send only the passages closest to the
  question.
- **Usage limits** per learner (`JAD_AI_HOURLY_LIMIT`, `JAD_AI_DAILY_LIMIT`),
  counted in Redis, or in the database when Redis is down.

## Prompt-injection defences

1. Learner text is Unicode-normalised, stripped of invisible and control
   characters, and capped (`JAD_AI_MAX_MESSAGE_CHARS`).
2. Obvious override attempts (ignore your instructions, show the system prompt,
   developer mode, fake role tags, smuggled base64) get a fixed reply and never
   reach the model.
3. Lesson text and the quiz question are fenced in tags with secret names, and
   anything resembling the fence is removed from them. The model is told that
   fenced text is data, not instructions.
4. The system prompt carries a secret canary. An answer containing it, or the
   fence name, is withheld and replaced as it streams.
5. Rendering on the frontend never uses HTML: answers become React elements
   only.

## Settings

`JAD_AI_ENABLED`, `JAD_AI_MODEL` (empty = `DEEPSEEK_MODEL`),
`JAD_AI_MAX_MESSAGE_CHARS`, `JAD_AI_MAX_ANSWER_TOKENS`, `JAD_AI_HOURLY_LIMIT`,
`JAD_AI_DAILY_LIMIT`, `JAD_AI_EMBEDDING_MODEL`, `JAD_AI_CACHE_DAYS`. It needs
`DEEPSEEK_API_KEY`.
