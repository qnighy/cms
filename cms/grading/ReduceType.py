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


"""This file abstracts out reducing strategy for subtasks.

Used in NamedGroup.
"""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

import json
import logging

from tornado.template import Template


logger = logging.getLogger(__name__)


class ReduceType(object):
    """Base class for all reduce types, that must implement all methods
    defined here.

    """
    TEMPLATE = ""

    def __init__(self, parameters):
        """Initializer.

        parameters (object): format is specified in the subclasses.

        """
        self.parameters = parameters

    def get_public_outcome(self, unused_outcome):
        """Return a public outcome from an outcome.

        The public outcome is shown to the user, and this method
        return the public outcome associated to the outcome of a
        submission in a testcase contained in the group identified by
        parameter.

        unused_outcome (float): the outcome of the submission in the
            testcase.

        return (float): the public output.

        """
        logger.error("Unimplemented method get_public_outcome.")
        raise NotImplementedError("Please subclass this class.")

    def reduce(self, unused_outcomes):
        """Return the score of a subtask given the outcomes.

        unused_outcomes ([float]): the outcomes of the submission in
            the testcases of the group.

        return (float): the public output.

        """
        logger.error("Unimplemented method reduce.")
        raise NotImplementedError("Please subclass this class.")
