import time


def outer(func):
    def inner(*args, **kwargs):
        n = time.time()
        func(*args, **kwargs)
        time.sleep(5)
        return time.time() - n, func(*args, **kwargs)

    return inner


@outer
def s(a, b):
    return a + b


print(s(4, 543))
