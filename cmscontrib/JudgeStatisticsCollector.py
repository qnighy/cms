#!/usr/bin/env python2
# -*- coding: utf-8 -*-

# Programming contest management system
# Copyright © 2014 Masaki Hara <ackie.h.gmai@gmail.com>
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
import datetime
import io
import json
import logging
import math
import os
import re

from tornado.template import Template

from cms.db import SessionGen, Contest, ask_for_contest,\
        User, Task, Submission, Testcase, Evaluation
from cms.db.filecacher import FileCacher
from cms.grading import task_score
from cms.grading.scoretypes import NamedGroup, get_score_type


logger = logging.getLogger(__name__)


class JudgeStatisticsCollector(object):

    """

    """

    TEMPLATE = u"""
<!doctype html>
<html>
    <head>
        <meta charset="utf-8">
        <title>Judge Statistics for {{ contest.name }}</title>
        <style>
        table tr:nth-child(odd) {
            background-color: #eee;
        }
        </style>
    </head>
    <body>
        <h1>Judge Statistics for {{ contest.name }}</h1>
        {% for task in tasks %}
            <h2>{{ task["title"] }}</h2>
            {% if "submissions" in task %}
            {% set subm_count = len(task["submissions"]) %}
            <p>Number of submissions: <strong>{{ subm_count }}</strong></p>
            {% end %}
            <p>Time Histogram:</p>
            <table>
                <tr>
                    <th>time</th>
                    <th>count</th>
                    <th>sum of wallclock time</th>
                </tr>
            {% for timespan in task["time_histogram"] %}
                <tr>
                    <td>{{ timespan["start"] }} - {{ timespan["end"] }}</td>
                    <td>{{ timespan["count"] }}</td>
                    <td>{{ "%.03f" % timespan["wallclock_time"] }}</td>
                </tr>
            {% end %}
            </table>
            {% if "testcase_summary" in task and subm_count > 0 %}
            <p>Testcase Summary:</p>
            <table>
                <tr>
                    <th>codename</th>
                    <th>average wallclock time</th>
                </tr>
            {% for testcase in task["testcase_summary"] %}
                <tr>
                    <td>{{ testcase["codename"] }}</td>
                    <td>{{ "%.03f" % (testcase["wallclock_time"] / subm_count) }}</td>
                </tr>
            {% end %}
            </table>
            {% end %}
            {% if "score_summary" in task %}
            <p>Score Summary:</p>
            <table>
                <tr>
                    <th>score</th>
                    <th>count</th>
                    <th>average wallclock time</th>
                </tr>
            {% for score_summary in task["score_summary"] %}
            {% if score_summary["count"] > 0 %}
                <tr>
                    <td>{{ score_summary["score"] }}</td>
                    <td>{{ score_summary["count"] }}</td>
                    <td>{{ "%.03f" % (score_summary["wallclock_time"] / score_summary["count"]) }}</td>
                </tr>
            {% end %}
            {% end %}
            </table>
            {% end %}
        {% end %}
    </body>
</html>
"""

    def __init__(self, contest_id, export_target):
        self.contest_id = contest_id

        # If target is not provided, we use the contest's name.
        if export_target == "":
            with SessionGen() as session:
                contest = Contest.get_from_id(self.contest_id, session)
                self.export_target = "judge_statistics_%s.html" % contest.name
                logger.warning("export_target not given, using \"%s\""
                               % self.export_target)
        else:
            self.export_target = export_target

        self.file_cacher = FileCacher()

    def do_export(self):
        """Run the actual export code."""
        logger.info("Starting export.")

        time_unit = 60.0 * 30.0

        export_file = self.export_target

        with SessionGen() as session,\
             io.open(export_file, "w", encoding="utf-8") as f:
            contest = Contest.get_from_id(self.contest_id, session)

            timespans = int(math.ceil((contest.stop - contest.start).total_seconds() / time_unit))

            tasks = []

            whole_data = {}
            whole_data["name"] = "All"
            whole_data["title"] = "All"
            whole_data["time_histogram"] = \
                    [{
                        'start': contest.start + datetime.timedelta(seconds=time_unit*i),
                        'end': contest.start + datetime.timedelta(seconds=time_unit*(i+1)),
                        'count': 0,
                        'wallclock_time': 0.0
                    } for i in range(timespans)]

            for task in session.query(Task)\
                    .filter(Task.contest == contest)\
                    .order_by(Task.num).all():
                dataset = task.active_dataset
                testcases = session.query(Testcase)\
                        .filter(Testcase.dataset == dataset)\
                        .order_by(Testcase.codename).all()
                scoretype = get_score_type(dataset=dataset)
                max_score = scoretype.max_scores()[0]

                task_data = {}
                task_data["name"] = task.name
                task_data["title"] = task.title
                task_data["score_summary"] = \
                        [{
                            'score': i,
                            'count': 0,
                            'wallclock_time': 0.0
                        } for i in range(int(math.ceil(max_score))+1)]
                task_data["testcase_summary"] = \
                        [{
                            'codename': testcase.codename,
                            'wallclock_time': 0.0
                        } for testcase in testcases]
                task_data["time_histogram"] = \
                        [{
                            'start': contest.start + datetime.timedelta(seconds=time_unit*i),
                            'end': contest.start + datetime.timedelta(seconds=time_unit*(i+1)),
                            'count': 0,
                            'wallclock_time': 0.0
                        } for i in range(timespans)]
                task_data["submissions"] = []
                for submission in session.query(Submission)\
                        .filter(Submission.task == task).all():
                    submission_result = submission.get_result(dataset)
                    submission_data = {}
                    task_data["submissions"].append(submission_data)
                    wallclock_time_sum = 0.0
                    for i, testcase in enumerate(testcases):
                        ev = session.query(Evaluation)\
                            .filter(Evaluation.submission_result == submission_result)\
                            .filter(Evaluation.testcase == testcase)\
                            .first()
                        wallclock_time_sum += ev.execution_wall_clock_time
                        task_data["testcase_summary"][i]['wallclock_time'] += ev.execution_wall_clock_time
                    time_idx = int((submission.timestamp - contest.start).total_seconds() / time_unit)
                    task_data["time_histogram"][time_idx]['count'] += 1
                    task_data["time_histogram"][time_idx]['wallclock_time'] += wallclock_time_sum
                    whole_data["time_histogram"][time_idx]['count'] += 1
                    whole_data["time_histogram"][time_idx]['wallclock_time'] += wallclock_time_sum
                    score = scoretype.compute_score(submission_result)[0]
                    task_data["score_summary"][int(score)]['count'] += 1
                    task_data["score_summary"][int(score)]['wallclock_time'] += wallclock_time_sum
                tasks.append(task_data)
            tasks.append(whole_data)

            f.write(unicode(Template(self.TEMPLATE).generate(
                    contest=contest, tasks=tasks), encoding="utf-8"))

        logger.info("Export finished.")

        return True


def main():
    """Parse arguments and launch process."""
    parser = argparse.ArgumentParser(description="Collects statistics of judging.")
    parser.add_argument("-c", "--contest-id", action="store", type=int,
                        help="id of contest to export")
    parser.add_argument("export_target", nargs='?', default="",
                        help="target file for export")

    args = parser.parse_args()

    if args.contest_id is None:
        args.contest_id = ask_for_contest()

    JudgeStatisticsCollector(contest_id=args.contest_id,
            export_target=args.export_target).do_export()


if __name__ == "__main__":
    main()
