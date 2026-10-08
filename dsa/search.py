def binary_search(items, target, key):
    low, high = 0, len(items) - 1
    while low <= high:
        mid = (low + high) // 2
        value = items[mid][key]
        if value == target:
            return items[mid]
        if value < target:
            low = mid + 1
        else:
            high = mid - 1
    return None
