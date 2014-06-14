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


class ShowUserList(object):

    """

    """

    def __init__(self, contest_id):
        self.contest_id = contest_id

    def do_export(self):
        """Run the actual export code."""
        logger.info("Starting export.")

        time_unit = 60.0 * 30.0

        with SessionGen() as session:
            contest = Contest.get_from_id(self.contest_id, session)

            for user in session.query(User)\
                    .filter(User.contest == contest)\
                    .order_by(User.id).all():
                print("%s,%s,%s,%s" %
                        (user.username, user.password,
                         user.first_name, user.last_name))

        logger.info("Export finished.")

        return True


def main():
    """Parse arguments and launch process."""
    parser = argparse.ArgumentParser(description="Collects statistics of judging.")
    parser.add_argument("-c", "--contest-id", action="store", type=int,
                        help="id of contest to export")

    args = parser.parse_args()

    if args.contest_id is None:
        args.contest_id = ask_for_contest()

    ShowUserList(contest_id=args.contest_id).do_export()


if __name__ == "__main__":
    main()
