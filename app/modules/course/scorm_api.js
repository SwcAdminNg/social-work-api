/*
 * Social Work Nigeria - SCORM runtime shim.
 *
 * Injected into the launch page of an interactive package served through
 * /scorm/{token}/... so the content finds a SCORM 1.2 API (window.API) and a
 * SCORM 2004 API (window.API_1484_11) on its own window - which is where every
 * common wrapper (ADL, pipwerks, Articulate, iSpring, hand-rolled findAPI loops)
 * looks first. Runtime data is kept in memory, seeded from the learner's saved
 * progress, and pushed back to the API on Commit/Finish (and shortly after any
 * SetValue, in case the package never commits). The parent page is told about
 * every change via postMessage so it can update the lesson UI live.
 */
(function () {
  var seed = window.__SWN_SCORM__ || {};
  var data = {};
  Object.keys(seed.data || {}).forEach(function (k) { data[k] = String(seed.data[k]); });
  var isLearn = seed.mode === "learn";
  var sessionId = seed.sessionId || String(Date.now()) + Math.random().toString(16).slice(2);
  var sessionStart = Date.now();
  var initialized = false, terminated = false, dirty = false, lastError = "0", timer = null;
  var resuming = !!(data["cmi.suspend_data"] || data["cmi.core.lesson_location"] || data["cmi.location"]);

  var defaults = {
    "cmi.core.student_id": seed.learnerId || "",
    "cmi.core.student_name": seed.learnerName || "",
    "cmi.core.lesson_location": "",
    "cmi.core.credit": "credit",
    "cmi.core.lesson_status": "not attempted",
    "cmi.core.entry": resuming ? "resume" : "ab-initio",
    "cmi.core.lesson_mode": isLearn ? "normal" : "browse",
    "cmi.core.total_time": seed.totalTime || "0000:00:00",
    "cmi.core.score.raw": "", "cmi.core.score.min": "", "cmi.core.score.max": "",
    "cmi.suspend_data": "",
    "cmi.launch_data": "",
    "cmi.comments": "",
    "cmi.student_data.mastery_score": "",
    "cmi.student_data.max_time_allowed": "",
    "cmi.student_data.time_limit_action": "",
    "cmi.student_preference.audio": "0", "cmi.student_preference.language": "",
    "cmi.student_preference.speed": "0", "cmi.student_preference.text": "0",
    // SCORM 2004
    "cmi.learner_id": seed.learnerId || "",
    "cmi.learner_name": seed.learnerName || "",
    "cmi.location": "",
    "cmi.completion_status": "unknown",
    "cmi.success_status": "unknown",
    "cmi.entry": resuming ? "resume" : "ab-initio",
    "cmi.mode": isLearn ? "normal" : "browse",
    "cmi.credit": "credit",
    "cmi.total_time": seed.totalTimeIso || "PT0S",
    "cmi.score.raw": "", "cmi.score.min": "", "cmi.score.max": "", "cmi.score.scaled": "",
    "cmi.progress_measure": "",
    "cmi.completion_threshold": "",
    "cmi.scaled_passing_score": "",
    "cmi.max_time_allowed": "",
    "cmi.time_limit_action": "continue,no message",
    "cmi.learner_preference.audio_level": "1", "cmi.learner_preference.language": "",
    "cmi.learner_preference.delivery_speed": "1", "cmi.learner_preference.audio_captioning": "0"
  };
  var children = {
    "cmi.core._children": "student_id,student_name,lesson_location,credit,lesson_status,entry,score,total_time,lesson_mode,exit,session_time",
    "cmi.core.score._children": "raw,min,max",
    "cmi.student_data._children": "mastery_score,max_time_allowed,time_limit_action",
    "cmi.student_preference._children": "audio,language,speed,text",
    "cmi.objectives._children": "id,score,status",
    "cmi.interactions._children": "id,objectives,time,type,correct_responses,weighting,student_response,result,latency",
    "cmi._version": "1.0",
    "cmi.score._children": "scaled,raw,min,max",
    "cmi.learner_preference._children": "audio_level,language,delivery_speed,audio_captioning",
    "cmi.comments_from_learner._children": "comment,location,timestamp",
    "cmi.comments_from_lms._children": "comment,location,timestamp"
  };
  var errorStrings = {
    "0": "No error", "101": "General exception", "201": "Invalid argument error",
    "301": "Not initialized", "401": "Not implemented error", "402": "Invalid set value, element is a keyword",
    "403": "Element is read only", "404": "Element is write only", "405": "Incorrect data type"
  };
  var readOnly = /^(cmi\.core\.(student_id|student_name|credit|entry|total_time|lesson_mode)|cmi\.launch_data|cmi\.student_data\..*|cmi\.(learner_id|learner_name|credit|entry|mode|total_time|launch_data|max_time_allowed|time_limit_action|completion_threshold|scaled_passing_score)|cmi\..*\._children|cmi\..*\._count|cmi\._version)$/;

  function count(prefix) {
    var ids = {};
    Object.keys(data).forEach(function (k) {
      var m = k.match(new RegExp("^" + prefix.replace(/\./g, "\\.") + "\\.(\\d+)\\."));
      if (m) ids[m[1]] = true;
    });
    return String(Object.keys(ids).length);
  }

  function getValue(key) {
    key = String(key);
    lastError = "0";
    if (Object.prototype.hasOwnProperty.call(data, key)) return data[key];
    if (Object.prototype.hasOwnProperty.call(children, key)) return children[key];
    if (Object.prototype.hasOwnProperty.call(defaults, key)) return defaults[key];
    var m = key.match(/^(cmi\.(?:objectives|interactions))\._count$/);
    if (m) return count(m[1]);
    m = key.match(/^(cmi\.interactions\.\d+\.(?:objectives|correct_responses))\._count$/);
    if (m) return count(m[1]);
    if (/^cmi\.(objectives|interactions)\.\d+\./.test(key)) return "";
    lastError = "401";
    return "";
  }

  function setValue(key, value) {
    key = String(key);
    lastError = "0";
    if (!initialized || terminated) { lastError = "301"; return "false"; }
    if (readOnly.test(key)) { lastError = "403"; return "false"; }
    data[key] = value === undefined || value === null ? "" : String(value);
    dirty = true;
    schedule();
    return "true";
  }

  function isCompleted() {
    var s = (data["cmi.core.lesson_status"] || "").toLowerCase();
    if (s === "completed" || s === "passed") return true;
    if ((data["cmi.completion_status"] || "").toLowerCase() === "completed") return true;
    if ((data["cmi.success_status"] || "").toLowerCase() === "passed") return true;
    return false;
  }

  function payload() {
    return {
      session_id: sessionId,
      session_seconds: Math.max(0, Math.round((Date.now() - sessionStart) / 1000)),
      data: data
    };
  }

  function notify(result) {
    try {
      window.parent.postMessage({
        type: "swn-scorm",
        event: result ? "committed" : "changed",
        completed: result && typeof result.is_completed === "boolean" ? result.is_completed : isCompleted(),
        lessonStatus: data["cmi.core.lesson_status"] || data["cmi.completion_status"] || "",
        successStatus: data["cmi.success_status"] || "",
        scoreRaw: data["cmi.core.score.raw"] || data["cmi.score.raw"] || "",
        location: data["cmi.core.lesson_location"] || data["cmi.location"] || "",
        saved: !!result
      }, "*");
    } catch (e) { /* no parent */ }
  }

  function schedule() {
    notify(null);
    if (!isLearn) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(function () { timer = null; commit(false); }, 2500);
  }

  function commit(final) {
    lastError = "0";
    if (timer) { clearTimeout(timer); timer = null; }
    if (!isLearn || !seed.commitUrl) { notify({ is_completed: isCompleted() }); return "true"; }
    var body = JSON.stringify(payload());
    dirty = false;
    try {
      fetch(seed.commitUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body,
        keepalive: !!final,
        credentials: "omit"
      }).then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) { notify((j && j.data) || { is_completed: isCompleted() }); })
        .catch(function () { dirty = true; });
    } catch (e) { dirty = true; }
    return "true";
  }

  function initialize() {
    lastError = "0";
    if (initialized && !terminated) { lastError = "101"; return "false"; }
    initialized = true; terminated = false; sessionStart = Date.now();
    notify(null);
    return "true";
  }

  function terminate() {
    lastError = "0";
    if (!initialized) { lastError = "301"; return "false"; }
    commit(true);
    terminated = true;
    return "true";
  }

  window.API = {
    LMSInitialize: initialize,
    LMSFinish: terminate,
    LMSGetValue: getValue,
    LMSSetValue: setValue,
    LMSCommit: function () { return commit(false); },
    LMSGetLastError: function () { return lastError; },
    LMSGetErrorString: function (code) { return errorStrings[String(code)] || ""; },
    LMSGetDiagnostic: function () { return ""; }
  };
  window.API_1484_11 = {
    Initialize: initialize,
    Terminate: terminate,
    GetValue: getValue,
    SetValue: setValue,
    Commit: function () { return commit(false); },
    GetLastError: function () { return lastError; },
    GetErrorString: function (code) { return errorStrings[String(code)] || ""; },
    GetDiagnostic: function () { return ""; }
  };

  window.addEventListener("pagehide", function () { if (initialized && !terminated && (dirty || isLearn)) commit(true); });
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden" && dirty) commit(true);
  });
  window.addEventListener("message", function (ev) {
    // The parent can ask for the current state (e.g. after it mounts late).
    if (ev && ev.data && ev.data.type === "swn-scorm-ping") notify(null);
  });
  notify(null);
})();
