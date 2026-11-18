"""JAD AI reads an interactive package's narration, panels and feedback, not just its visible markup."""

from app.modules.jad_ai.material import html_to_text, scorm_to_text

PACKAGE = r"""<!doctype html><html><head><title>4.2 Structured safety thinking</title>
<style>.card{color:red}</style></head><body>
<h2>The SAFER pathway</h2>
<button>Back</button><button>Next</button><button>Read text</button>
<script>
var TRACKS = {"c5-1": {"src": "assets/audio/c5-1.mp3",
  "vo": "S. Scan. What danger, injury or urgent health need exists now?",
  "cues": [], "caps": [[0.07, "S."], [0.68, "Scan."]]}};
var CARDS = [{"col": "blue", "track": "c5-2",
  "html": "<div class=\"dtext\"><h3>A &middot; Act</h3><p>What can I lawfully and safely do now?</p></div>"}];
const FEEDBACK = {correct: 'Yes - keep her supervised and use the urgent procedure now.',
  incorrect: "Waiting for proof leaves the child exposed."};
function go(n) { return document.querySelector('.card-' + n).classList.add('open'); }
var css = "rgba(0,0,0,.4) 12px";
</script></body></html>"""


def test_scorm_text_includes_scripted_lesson_words():
    text = scorm_to_text(PACKAGE)
    assert "The SAFER pathway" in text
    assert "What danger, injury or urgent health need exists now?" in text   # narration ("vo")
    assert "A · Act" in text and "What can I lawfully and safely do now?" in text  # panel HTML
    assert "keep her supervised and use the urgent procedure now" in text   # single-quoted feedback
    assert "Waiting for proof leaves the child exposed." in text


def test_scorm_text_skips_code_assets_and_player_chrome():
    text = scorm_to_text(PACKAGE)
    assert "assets/audio" not in text and ".mp3" not in text
    assert "querySelector" not in text and "rgba" not in text
    assert "color:red" not in text
    for chrome in ("Back", "Next", "Read text"):
        assert chrome not in text.splitlines()
    # Captions repeat the narration; they are not added again.
    assert text.count("Scan") == 1


def test_scorm_text_is_a_superset_of_the_old_reader():
    old = html_to_text(PACKAGE)
    new = scorm_to_text(PACKAGE)
    assert len(new) > len(old)
    assert "What can I lawfully and safely do now?" not in old
