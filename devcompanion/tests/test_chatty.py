from devcompanion.pulled import chatty

DIFF = """diff --git a/src/shop/log.py b/src/shop/log.py
index 1111111..2222222 100644
--- a/src/shop/log.py
+++ b/src/shop/log.py
@@ -1,3 +1,3 @@
 import logging
-FORMAT = "%(message)s"
+FORMAT = "%(name)s: %(message)s"
diff --git a/tests/test_paging.py b/tests/test_paging.py
new file mode 100644
--- /dev/null
+++ b/tests/test_paging.py
@@ -0,0 +1,2 @@
+def test_page():
+    assert True
diff --git a/src/old.py b/src/old.py
deleted file mode 100644
--- a/src/old.py
+++ /dev/null
@@ -1 +0,0 @@
-x = 1
"""


def test_diff_stats_counts_files_and_lines_across_new_and_deleted_files():
    assert chatty.diff_stats(DIFF) == "3 files changed, +3 -2: src/shop/log.py, tests/test_paging.py, src/old.py"


def test_summary_and_commit_packets_lead_with_the_diff_statistics():
    for function in ("summary", "commit"):
        assert chatty.packet(function, DIFF).startswith("Diff statistics: 3 files changed, +3 -2")


def test_plan_packet_carries_the_goal_and_the_file():
    assert chatty.packet("plan", "def f(): ...", "src/a.py", "rename f") == \
        "File: src/a.py\nGoal: rename f\n\ndef f(): ..."


def test_grill_packet_lists_the_questions_already_asked():
    assert chatty.packet("grill", "x = 1", "a.py", history=[("Why `x`?", "Fair point.")]) == \
        "File: a.py\n\nx = 1\n\nAlready asked:\nQ: Why `x`?\nA: Fair point."


def test_no_challenge_is_read_through_punctuation_but_not_inside_a_sentence():
    assert chatty.no_challenge("NO CHALLENGE.") and chatty.no_challenge("`NO CHALLENGE`\n")
    assert not chatty.no_challenge("No challenge here, but what about `nan`?")


def test_shape_commit_strips_the_period_and_reports_a_long_subject_without_cutting_it():
    subject = "Update log format to include logger name and add customer blocking check."
    shaped = chatty.shape_commit(f"subject: {subject}\nbody:")
    assert shaped == {"subject": subject[:-1], "body": [], "problems": ["subject 72 characters"]}


def test_shape_commit_reads_a_multiline_body_and_drops_a_placeholder_one():
    shaped = chatty.shape_commit("subject: Add paging tests\nbody: Covers page 0.\nAnd partial pages.")
    assert shaped["body"] == ["Covers page 0.", "And partial pages."] and not shaped["problems"]
    assert chatty.shape_commit("subject: Rename calc\nbody: (empty)")["body"] == []


def test_the_local_grill_is_the_judged_three_question_prompt_and_the_flagship_asks_one_richer_question():
    assert chatty.prompt_id("grill") == "46db502e", "the local grill must stay the prompt that was judged"
    assert chatty.system("grill") == chatty.SYSTEM["grill"]
    flagship = chatty.system("grill", remote=True)
    assert "question:" in flagship and "why it matters:" in flagship and chatty.NO_CHALLENGE in flagship
    assert chatty.system("commit", remote=True) == chatty.SYSTEM["commit"]


def test_every_function_has_a_prompt_and_a_budget():
    assert set(chatty.SYSTEM) == set(chatty.TOKENS) == set(chatty.FUNCTIONS)
    assert len({chatty.prompt_id(f) for f in chatty.FUNCTIONS}) == len(chatty.FUNCTIONS)
