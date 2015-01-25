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
import logging

from cms import plugin_lookup


logger = logging.getLogger(__name__)


def get_reduce_type_class(name):
    """Load the ReduceType class given as parameter."""
    return plugin_lookup(name,
                         "cms.grading.reducetypes", "reducetypes")


def get_reduce_type(name=None, parameters=None):
    """Construct the ReduceType specified by parameters.

    Load the ReduceType class named "name" and instantiate it with the
    data structure obtained by JSON-decoded "parameters".

    name (unicode|None): the name of the ReduceType class.
    parameters: the JSON-decoded parameters.

    return (ReduceType): an instance of the correct ReduceType class.

    """
    class_ = get_reduce_type_class(name)

    return class_(parameters)
