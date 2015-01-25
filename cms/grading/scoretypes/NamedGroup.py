#!/usr/bin/env python2
# -*- coding: utf-8 -*-

# Contest Management System - http://cms-dev.github.io/
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

from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

import json

from cms.grading.ScoreType import ScoreTypeAlone
from cms.grading.reducetypes import get_reduce_type


# Dummy function to mark translatable string.
def N_(message):
    return message


class NamedGroup(ScoreTypeAlone):
    """Class to manage tasks whose testcases belong to
    arbitrary number of subtasks. The score type parameters must be
    in the form [{ 'name': name, 'max_score': score,
    'testcases': [t1, t2, ...], 'reduce': reduce }, ...], where name
    is the name of the subtask, score is the maximum score for the
    subtask, t is the list of testcases included in the subtask, and
    reduce is a reducing strategy for the subtask.
    """
    # Mark strings for localization.
    N_("Outcome")
    N_("Details")
    N_("Execution time")
    N_("Memory used")
    N_("N/A")
    TEMPLATE = """\
{% from cms.grading import format_status_text %}
{% from cms.server import format_size %}
{% for st in details %}
    {% if "score" in st and "max_score" in st %}
        {% if st["reduced_outcome"] >= 1.0 %}
<div class="subtask correct">
        {% elif st["reduced_outcome"] <= 0.0 %}
<div class="subtask notcorrect">
        {% else %}
<div class="subtask partiallycorrect">
        {% end %}
    {% else %}
<div class="subtask undefined">
    {% end %}
    <div class="subtask-head">
        <span class="title">
            {{ st["name"] }}
        </span>
    {% if "score" in st and "max_score" in st %}
        <span class="score">
            {{ '%g' % round(st["score"], 2) }} / {{ st["max_score"] }}
        </span>
    {% else %}
        <span class="score">
            {{ _("N/A") }}
        </span>
    {% end %}
    </div>
    <div class="subtask-body">
        <table class="testcase-list">
            <thead>
                <tr>
                    <th>{{ _("Outcome") }}</th>
                    <th>{{ _("Details") }}</th>
                    <th>{{ _("Execution time") }}</th>
                    <th>{{ _("Memory used") }}</th>
                </tr>
            </thead>
            <tbody>
    {% for tc in st["testcases"] %}
        {% if "outcome" in tc and "text" in tc %}
            {% if tc["outcome"] == "Correct" %}
                <tr class="correct">
            {% elif tc["outcome"] == "Not correct" %}
                <tr class="notcorrect">
            {% else %}
                <tr class="partiallycorrect">
            {% end %}
                    <td>{{ _(tc["outcome"]) }}</td>
                    <td>{{ format_status_text(tc["text"], _) }}</td>
                    <td>
            {% if "time" in tc and tc["time"] is not None %}
                        {{ _("%(seconds)0.3f s") % {'seconds': tc["time"]} }}
            {% else %}
                        {{ _("N/A") }}
            {% end %}
                    </td>
                    <td>
            {% if "memory" in tc and tc["memory"] is not None %}
                        {{ format_size(tc["memory"]) }}
            {% else %}
                        {{ _("N/A") }}
            {% end %}
                    </td>
        {% else %}
                <tr class="undefined">
                    <td colspan="4">
                        {{ _("N/A") }}
                    </td>
                </tr>
        {% end %}
    {% end %}
            </tbody>
        </table>
    </div>
</div>
{% end %}"""

    def max_scores(self):
        """See ScoreType.max_score."""
        score = 0.0
        public_score = 0.0
        headers = list()

        for i, parameter in enumerate(self.parameters):
            score += parameter['max_score']
            if all(self.public_testcases[f]
                   for f in parameter['testcases']):
                public_score += parameter['max_score']
            headers += ["%s (%g)" % (parameter['name'], parameter['max_score'])]

        return score, public_score, headers

    def compute_score(self, submission_result):
        """See ScoreType.compute_score."""
        # Actually, this means it didn't even compile!
        if not submission_result.evaluated():
            return 0.0, "[]", 0.0, "[]", \
                json.dumps(["%lg" % 0.0 for _ in self.parameters])

        evaluations = dict((ev.codename, ev)
                           for ev in submission_result.evaluations)
        subtasks = []
        public_subtasks = []
        ranking_details = []

        for st_idx, parameter in enumerate(self.parameters):
            reduce_type = get_reduce_type(parameter['reduce'], parameter.get('reduce_parameters'))
            st_reduced_outcome = reduce_type.reduce((float(evaluations[f].outcome)
                for f in parameter['testcases']))
            st_score = st_reduced_outcome * parameter['max_score']
            st_public = all(self.public_testcases[f]
                            for f in parameter['testcases'])
            tc_outcomes = dict((
                f,
                reduce_type.get_public_outcome(
                    float(evaluations[f].outcome))
                ) for f in parameter['testcases'])

            testcases = []
            public_testcases = []
            for f in parameter['testcases']:
                testcases.append({
                    "testcase": f,
                    "outcome": tc_outcomes[f],
                    "text": evaluations[f].text,
                    "time": evaluations[f].execution_time,
                    "memory": evaluations[f].execution_memory,
                    })
                if self.public_testcases[f]:
                    public_testcases.append(testcases[-1])
                else:
                    public_testcases.append({"f": f})
            subtasks.append({
                "name": parameter['name'],
                "reduced_outcome": st_reduced_outcome,
                "score": st_score,
                "max_score": parameter['max_score'],
                "testcases": testcases,
                })
            if st_public:
                public_subtasks.append(subtasks[-1])
            else:
                public_subtasks.append({
                    "name": parameter['name'],
                    "testcases": public_testcases,
                    })

            ranking_details.append("%g" % round(st_score, 2))

        score = sum(st["score"] for st in subtasks)
        public_score = sum(st["score"]
                           for st in public_subtasks
                           if "score" in st)

        return score, json.dumps(subtasks), \
            public_score, json.dumps(public_subtasks), \
            json.dumps(ranking_details)
