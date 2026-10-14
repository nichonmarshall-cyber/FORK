"""Persistence for the student notebook: accounts, documents, facts, history.

Only the account and command-center data lives here. The audit review flow
(upload, correct, confirm) still runs on the in-memory session store; a
student explicitly saves a confirmed result into their notebook, and that is
the moment anything about it becomes durable.
"""
