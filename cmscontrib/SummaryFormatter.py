#!/usr/bin/env python2
# -*- coding: utf-8 -*-

# Programming contest management system
# Copyright © 2015 Masaki Hara <ackie.h.gmai@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# We enable monkey patching to make many libraries gevent-friendly
# (for instance, urllib3, used by requests)
import gevent.monkey
gevent.monkey.patch_all()

import argparse
import io
import json
import logging

from tornado.template import Template

from cms.db import SessionGen, Contest, ask_for_contest,\
    User, Task, Submission, Testcase, Evaluation
from cms.db.filecacher import FileCacher
from cms.grading import task_score
from cms.grading.scoretypes import get_score_type


logger = logging.getLogger(__name__)


def tex_escape(s):
    from tornado.escape import to_unicode
    ret = []
    for x in to_unicode(s):
        if x == '#' or x == '$' or x == '%' or x == '&' or x == '_' or \
                x == '{' or x == '}':
            ret.append("\\")
        # if x == '\\' or x == '|' or x == '*' or x == '<' or x == '>' or \
        if x == '\\' or x == '|' or x == '<' or x == '>' or \
                x == '^' or x == '~':
            ret.append("\\char'\\")
        ret.append(x)
    return u"".join(ret)


def testcase_prefixes(testcases_all, testcases):
    prefixes = []
    for pref_testcase in testcases:
        for i in range(len(pref_testcase)):
            if i > 0 and pref_testcase[i-1] != '-':
                continue
            prefix = pref_testcase[0:i]
            if all(testcase in testcases
                    for testcase in testcases_all
                    if testcase.startswith(prefix)):
                prefixes.append(prefix + u"*")
                testcases = \
                    [testcase for testcase in testcases
                        if not testcase.startswith(prefix)]
    return prefixes + testcases


class SummaryFormatter(object):

    """

    """

    TEMPLATE = u"""
{% from cms.server import format_size %}
\\documentclass[10pt,a4j,notitlepage,uplatex]{jsarticle}
\\bibliographystyle{jplain}
\\title{成績表}
\\author{}
\\usepackage{array}
\\usepackage[usenames,dvipsnames,svgnames,table]{xcolor}
\\usepackage{multicol}
\\usepackage{setspace}
\\usepackage[cm]{fullpage}
\\usepackage{fancyhdr}
\\pagestyle{fancy}
\\lhead{ {{ contest.description }} 成績表}
\\begin{document}

summary
\\newpage
\\setcounter{page}{1}
{% for user in users %}
    \\def\\username{ {{ user["username"] }} }
    \\def\\firstname{ {{ user["first_name"] }} }
    \\def\\lastname{ {{ user["last_name"] }} }
    \\section*{成績表: \\username \\lastname \\firstname}
    \\rhead{\\lastname \\firstname \\username}
    {% set table_len = len(user["tasks"]) + 1 %}
    {% set table_width = 15.0 / table_len %}
    \\begin{tabular}{ {% raw ("|m{%gcm}" % table_width) * table_len %}| }
    \\hline
    {% for task in user["tasks"] %}
        \\cellcolor{SkyBlue} {{ task["title"] }} &
    {% end %}
    \\cellcolor{Salmon} 合計 \\\\
    \\hline
    {% for task in user["tasks"] %}
        {{ "%g" % task["score"] }} / {{ "%g" % task["max_score"] }} &
    {% end %}
    {{ "%g" % user["score"] }} / {{ "%g" % user["max_score"] }} \\\\
    \\hline
    \\end{tabular}
    \\begin{multicols}{3}
    \\begin{spacing}{0.8}
    {% for task in user["tasks"] %}
        \subsection*{ {{ task["title"] }} }

        \\begin{description}
            \\item[------]
            \\makebox[8mm]{ 結果 }
            \\makebox[14mm]{ 時間 }
            \\makebox[14mm]{ メモリ }
        {% for testcase in task["testcases"] %}
            {% set x = testcase["text"] != "N/A" %}
            {% set y = \
                 format_size(testcase["execution_memory"]).replace(" ","") %}
            \\item[{{ testcase["name"] }}]
            \\makebox[8mm]{ {{ testcase["text"] }} } {% if x %}
            \\makebox[14mm]{ {{ "%.3fs" % testcase["execution_time"] }} }
            \\makebox[14mm]{ {{ y }} }
            {% end %}
        {% end %}
        \\end{description}

        \\begin{description}
        {% for subtask in task["subtasks"] %}
            \\item[{{ subtask["name"] }}]
            {{ u",".join(subtask["testcases"]) }}
            {{ "%g" % subtask["score"] }}/{{ "%g" % subtask["max_score"] }}
        {% end %}
        \\end{description}
    {% end %}
    \\end{spacing}
    \\end{multicols}
    \\newpage
    \\setcounter{page}{1}
{% end %}
\\end{document}
"""

    def __init__(self, contest_id, export_target):
        self.contest_id = contest_id

        # If target is not provided, we use the contest's name.
        if export_target == "":
            with SessionGen() as session:
                contest = Contest.get_from_id(self.contest_id, session)
                self.export_target = "summary_%s.tex" % contest.name
                logger.warning("export_target not given, using \"%s\""
                               % self.export_target)
        else:
            self.export_target = export_target

        self.file_cacher = FileCacher()

    def do_export(self):
        """Run the actual export code."""
        logger.info("Starting export.")

        export_file = self.export_target

        with \
                SessionGen() as session,\
                io.open(export_file, "w", encoding="utf-8") as f:
            contest = Contest.get_from_id(self.contest_id, session)

            logger.info("contest is %s" % str(contest))
            users = []
            for user in session.query(User)\
                    .filter(User.contest == contest)\
                    .order_by(User.username).all():
                user_data = {}
                user_data["username"] = user.username
                user_data["first_name"] = user.first_name
                user_data["last_name"] = user.last_name
                score = 0.0
                max_score = 0.0
                user_data["tasks"] = []
                for task in session.query(Task)\
                        .filter(Task.contest == contest)\
                        .order_by(Task.num).all():
                    task_data = {}
                    task_data["title"] = task.title
                    t_score, t_partial = task_score(user, task)
                    t_max_score = 100.0   # TODO
                    task_data["score"] = round(t_score, task.score_precision)
                    task_data["max_score"] = \
                        round(t_max_score, task.score_precision)
                    score += t_score
                    max_score += t_max_score
                    t_submission = None
                    t_submission_r = None
                    for s in session.query(Submission)\
                            .filter(Submission.user == user)\
                            .filter(Submission.task == task)\
                            .order_by(Submission.timestamp).all():
                        sr = s.get_result(task.active_dataset)
                        if sr is not None and sr.scored()\
                                and sr.compilation_outcome != "fail"\
                                and sr.score == t_score:
                            t_submission = s
                            t_submission_r = sr
                    if t_submission is None:
                        testcases_data = []
                        task_data["testcases"] = testcases_data
                        all_testcases = []
                        for testcase in session.query(Testcase)\
                                .filter(Testcase.dataset
                                        == task.active_dataset)\
                                .order_by(Testcase.codename).all():
                            t_data = {}
                            all_testcases.append(testcase.codename)
                            testcases_data.append(t_data)
                            t_data["name"] = testcase.codename
                            t_data["outcome"] = 0.0
                            t_data["text"] = "N/A"
                            t_data["execution_time"] = 0.0
                            t_data["execution_memory"] = 0
                        subtasks_data = []
                        task_data["subtasks"] = subtasks_data
                        parameters = json.loads(
                            task.active_dataset.score_type_parameters)
                        for subtask in parameters:
                            subtask_data = {}
                            subtask_data["name"] = subtask["name"]
                            subtask_data["score"] = 0.0
                            subtask_data["max_score"] = \
                                float(subtask["max_score"])
                            subtask_data["testcases"] = \
                                testcase_prefixes(all_testcases,
                                                  subtask["testcases"])
                            subtasks_data.append(subtask_data)
                    else:
                        testcases_data = []
                        task_data["testcases"] = testcases_data
                        all_testcases = []
                        for testcase in session.query(Testcase)\
                                .filter(Testcase.dataset
                                        == task.active_dataset)\
                                .order_by(Testcase.codename).all():
                            t_data = {}
                            all_testcases.append(testcase.codename)
                            testcases_data.append(t_data)
                            ev = session.query(Evaluation)\
                                .filter(Evaluation.submission_result
                                        == t_submission_r)\
                                .filter(Evaluation.testcase == testcase)\
                                .first()
                            t_data["name"] = testcase.codename
                            t_data["outcome"] = ev.outcome
                            text = ev.text
                            if text.find("Output is correct") >= 0:
                                text = "AC"
                            elif text.find("Output isn't correct") >= 0:
                                text = "WA"
                            elif text.find("Execution timed out") >= 0:
                                text = "TLE"
                            elif text.find("Execution killed") >= 0:
                                text = "RE"
                            elif text.find("Execution failed") >= 0:
                                text = "RE"
                            else:
                                logger.warning(
                                    "Unknown text for evaluation: %s.", text)
                            t_data["text"] = text
                            t_data["execution_time"] = ev.execution_time
                            t_data["execution_memory"] = ev.execution_memory
                        subtasks_data = []
                        task_data["subtasks"] = subtasks_data
                        scoretype = get_score_type(dataset=task.active_dataset)
                        subtasks = json.loads(
                            scoretype.compute_score(t_submission_r)[1])
                        # logger.info("subtasks = %s" % str(subtasks))
                        for subtask in subtasks:
                            subtask_data = {}
                            subtask_data["name"] = subtask["name"]
                            subtask_data["score"] = float(subtask["score"])
                            subtask_data["max_score"] = \
                                float(subtask["max_score"])
                            subtask_data["testcases"] = \
                                testcase_prefixes(all_testcases,
                                        [tc["testcase"] for tc
                                            in subtask["testcases"]])
                            subtasks_data.append(subtask_data)
                    user_data["tasks"].append(task_data)
                user_data["score"] = round(score, contest.score_precision)
                user_data["max_score"] = \
                    round(max_score, contest.score_precision)
                users.append(user_data)

            f.write(unicode(Template(self.TEMPLATE,
                    autoescape="tex_escape").generate(
                contest=contest,
                users=users,
                tex_escape=tex_escape), encoding="utf-8"))

        logger.info("Export finished.")

        return True


def main():
    """Parse arguments and launch process."""
    parser = argparse.ArgumentParser(
        description="Outputs summary for each contestants.")
    parser.add_argument("-c", "--contest-id", action="store", type=int,
                        help="id of contest to export")
    parser.add_argument("export_target", nargs='?', default="",
                        help="target file for export")

    args = parser.parse_args()

    if args.contest_id is None:
        args.contest_id = ask_for_contest()

    SummaryFormatter(contest_id=args.contest_id,
                     export_target=args.export_target).do_export()


if __name__ == "__main__":
    main()
