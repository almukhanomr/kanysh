"""Small floating-point expansions for exact block sums without retaining blocks."""


class Fsum:
    """Non-overlapping partials, finalized with math.fsum by the consumer.

    Error-free TwoSum retains rounded-away bits. Memory depends on exponent
    range rather than the number of cells, blocks or Monte Carlo samples.
    """

    def __init__(self):
        self.partials = []

    def append(self, value):
        partials = self.partials
        i = 0
        x = float(value)
        for y in partials:
            if abs(x) < abs(y):
                x, y = y, x
            high = x + y
            low = y - (high - x)
            if low:
                partials[i] = low
                i += 1
            x = high
        partials[i:] = [x]

    def extend(self, values):
        for value in values:
            self.append(value)

    def __iter__(self):
        return iter(self.partials)
