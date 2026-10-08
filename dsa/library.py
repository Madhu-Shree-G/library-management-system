from .queue import Queue
from .stack import Stack
from .sorting import merge_sort
from .search import binary_search

class Library:
    def __init__(self):
        self.books = []
        self.next_id = 1
        self.borrow_queue = Queue()
        self.recent_activity = Stack()

    def add_book(self, title, author, category):
        book = {
            "id": self.next_id,
            "title": title,
            "author": author,
            "category": category,
            "available": True,
        }
        self.books.append(book)
        self.next_id += 1
        self.recent_activity.push(f"Added: {title}")

    def search(self, query):
        query = query.lower()
        return [b for b in self.books if query in b["title"].lower() or query in b["author"].lower() or query in b["category"].lower()]

    def borrow_book(self, book_id):
        book = binary_search(self._sorted_books(), book_id, key="id")
        if book and book["available"]:
            book["available"] = False
            self.borrow_queue.enqueue(book["id"])
            self.recent_activity.push(f"Borrowed: {book['title']}")

    def return_book(self, book_id):
        book = binary_search(self._sorted_books(), book_id, key="id")
        if book and not book["available"]:
            book["available"] = True
            self.recent_activity.push(f"Returned: {book['title']}")

    def _sorted_books(self):
        return merge_sort(self.books, key="id")

    def stats(self):
        total = len(self.books)
        available = sum(b["available"] for b in self.books)
        return {"total": total, "available": available, "borrowed": total - available}
