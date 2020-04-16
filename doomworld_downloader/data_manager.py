class DataManager:
    """Manages & decides on possible and confirmed demo data

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
        self.data = {}

    def insert(self, field, value, certainty):
        self.__ensure_field_exists(field)

        self.data[field].insert(value, certainty)

    def evaluate(self, field):
        self.__ensure_field_exists(field)

        return self.data[field].evaluate()

    def __ensure_field_exists(self, field):
        if field not in self.data:
            self.data[field] = self.FieldManager()

    class FieldManager:
        """Manages the value hierarchy of a field"""

        def __init__(self):
            self.data = {
                DataManager.CERTAIN: {},
                DataManager.POSSIBLE: {}
            }

        def insert(self, value, certainty):
            if value not in self.data[certainty]:
                self.data[certainty][value] = self.ValueCounter(value)

            self.data[certainty][value].increment()

        # This is quite verbose, but inevitably there are a lot of cases
        def evaluate(self):
            certain_count = len(self.__certain())
            possible_count = len(self.__possible())

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
                    if self.__possible().values()[0].agreement():
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

            return self.Evaluation(possible_values, needs_attention, message)

        def __certain(self):
            return self.data[DataManager.CERTAIN]

        def __possible(self):
            return self.data[DataManager.POSSIBLE]

        def __raw_values(self, value_dict):
            value_counters = value_dict.values()
            return list(map(lambda x: x.value, value_counters))

        class ValueCounter:
            """Counts the number of times a value is reported"""

            def __init__(self, value):
                self.value = value
                self.count = 0

            def increment(self):
                self.count += 1

            def agreement(self):
                return self.count > 1

        class Evaluation:
            """Contains the final evaluation of a field"""

            def __init__(self, possible_values, needs_attention, message):
                self.possible_values = possible_values
                self.needs_attention = needs_attention
                self.message = message
