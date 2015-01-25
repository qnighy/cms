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

from cms.grading.ReduceType import ReduceType


# Dummy function to mark translatable string.
def N_(message):
    return message


class Threshold(ReduceType):
    """The score of a submission is the sum of: the multiplier of the
    range if all outcomes are between the threshold and 1.0, or 0.0.

    Parameters are {"threshold":threshold}.

    """

    def get_public_outcome(self, outcome):
        """See ReduceType."""
        threshold = self.parameters['threshold']
        if threshold <= outcome <= 1.0:
            return N_("Correct")
        else:
            return N_("Not correct")

    def reduce(self, outcomes):
        """See ReduceType."""
        threshold = self.parameters['threshold']
        if all(threshold <= outcome <= 1.0
               for outcome in outcomes):
            return 1.0
        else:
            return 0.0
