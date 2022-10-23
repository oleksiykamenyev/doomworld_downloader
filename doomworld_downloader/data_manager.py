"""Data manager module."""


class DataManager:
    """Manage & decide on possible and confirmed demo data.

    Example usage:

    dm = DataManager()

    # CERTAIN values don't need attention
    dm.insert('complevel', 3, DataManager.CERTAIN)
    evaluation = dm.evaluate('complevel')
    evaluation.possible_values # [3]
    evaluation.needs_attention # False
    evaluation.message # 'The value is certain'

    # Mismatched POSSIBLE values need attention
    dm.insert('category', 'Pacifist', DataManager.POSSIBLE)
    dm.insert('category', 'UV Speed', DataManager.POSSIBLE)
    evaluation = dm.evaluate('category')
    evaluation.possible_values # ['Pacifist', 'UV Speed']
    evaluation.needs_attention # True
    evaluation.message # 'Multiple sources disagreed on the possible value'

    # CERTAIN values override POSSIBLE values
    dm.insert('category', 'Pacifist', DataManager.CERTAIN)
    dm.evaluate('category').possible_values # ['Pacifist']
    """

    CERTAIN = 'certain'
    POSSIBLE = 'possible'
    ONE_CERTAIN = 'The value is certain'
    ONE_POSSIBLE = 'Only one source reported a possible value'
    AGREED_POSSIBLE = 'Multiple sources agreed on the possible value'
    DISAGREED_CERTAIN = 'Multiple sources disagreed on the certain value'
    DISAGREED_POSSIBLE = 'Multiple sources disagreed on the possible value'
    NO_VALUE = 'No source reported any value'

    def __init__(self):
        """Initialize data manager."""
        self.data = {}

    def __iter__(self):
        """Iterate over evaluations of every field in the data manager."""
        return (self.data[field].evaluate() for field in self.data)

    def insert(self, field, value, certainty, source=None):
        """Insert new field and value into the data manager.

        If the field already exists in the manager, it will just be incremented, and a new source
        will be added.

        :param field: Field key
        :param value: Field value
        :param certainty: Level of certainty for field (certain or possible)
        :param source: Source of field (e.g., playback, textfile)
        """
        self.__ensure_field_exists(field)

        self.data[field].insert(value, certainty, source=source)

    def evaluate(self, field):
        """Evaluate whether a field needs further attention.

        Fields need attention if there are disagreeing values, there is just a single possible
        guess, or there is no value for a field.

        :param field: Field to evaluate
        :return: Evaluation of field
        """
        self.__ensure_field_exists(field)

        return self.data[field].evaluate()

    def __ensure_field_exists(self, field):
        """Ensure that a field already exists in the data manager.

        :param field: Field to ensure existence for
        """
        if field not in self.data:
            self.data[field] = self.FieldManager(field)

    class FieldManager:
        """Manage the value hierarchy of a field."""
        def __init__(self, field):
            """Initialize field manager.

            :param field: Field key to initialize field manager for.
            """
            self.field = field
            self.data = {DataManager.CERTAIN: {}, DataManager.POSSIBLE: {}}

        def insert(self, value, certainty, source=None):
            """Insert new value into field manager.

            :param value: Value to insert.
            :param certainty: Level of certainty for field (certain or possible)
            :param source: Source of field (e.g., playback, textfile)
            """
            if value not in self.data[certainty]:
                self.data[certainty][value] = self.ValueCounter(value)

            self.data[certainty][value].increment()
            self.data[certainty][value].add_source(source)

        def evaluate(self):
            """Evaluate a field within the field manager.

            This is quite verbose, but inevitably there are a lot of cases
            """
            certain_count = len(self.__certain())
            possible_count = len(self.__possible())

            # It is practically impossible for these to remain undefined, but setting defaults
            # anyway so the editor doesn't get angry... :P
            needs_attention = None
            message = None
            if certain_count > 0:
                possible_values = self.__raw_values(self.__certain())

                if certain_count == 1:
                    needs_attention = False
                    message = DataManager.ONE_CERTAIN
                elif certain_count > 1:
                    needs_attention = True
                    message = DataManager.DISAGREED_CERTAIN
            elif possible_count > 0:
                possible_values = self.__raw_values(self.__possible())

                if possible_count == 1:
                    if list(self.__possible().values())[0].agreement():
                        needs_attention = False
                        message = DataManager.AGREED_POSSIBLE
                    else:
                        needs_attention = True
                        message = DataManager.ONE_POSSIBLE
                else:
                    needs_attention = True
                    message = DataManager.DISAGREED_POSSIBLE
            else:
                possible_values = []
                needs_attention = True
                message = DataManager.NO_VALUE

            return self.Evaluation(self.field, possible_values, needs_attention, message)

        def __certain(self):
            """Return all certain values inside the field.

            :return: All certain values inside the field
            """
            return self.data[DataManager.CERTAIN]

        def __possible(self):
            """Return all possible values inside the field.

            :return: All possible values inside the field
            """
            return self.data[DataManager.POSSIBLE]

        @staticmethod
        def __raw_values(value_dict):
            """Return raw values mapped to sources inside value dict.

            :param value_dict: Value dictionary
            :return: Raw values mapped to sources
            """
            value_counters = value_dict.values()
            return {x.value: x.sources for x in value_counters}

        class ValueCounter:
            """Count the number of times a value is reported."""
            def __init__(self, value):
                """Initialize value counter

                :param value: Value to initialize for.
                """
                self.value = value
                self.count = 0
                self.sources = []

            def increment(self):
                """Increment counter."""
                self.count += 1

            def agreement(self):
                """Return if there are multiple agreeing sources on this value.

                :return: Flag indicating if there are multiple agreeing sources on this value.
                """
                return self.count > 1

            def add_source(self, source):
                """Add source to value sources list.

                :param source: Source to add
                """
                if source:
                    self.sources.append(source)

        class Evaluation:
            """Contains the final evaluation of a field."""
            def __init__(self, key, possible_values, needs_attention, message):
                """Initialize field evaluation.

                :param key: Field key
                :param possible_values: Possible values for field
                :param needs_attention: Flag indicating whether this field needs further manual
                                        attention
                :param message: Detailed message about evaluation.
                """
                self.key = key
                self.possible_values = possible_values
                self.needs_attention = needs_attention
                self.message = message

            def __str__(self):
                """Convert evaluation to string for ease of debugging.

                :return: Evaluation as string.
                """
                return 'Evaluation(key={},possible_values={},needs_attention={},message={})'.format(
                    self.key, self.possible_values, self.needs_attention, self.message
                )
