"""
The suggestion chips under Ask Fork, recognised server-side.

Each chip sends a fixed question whose topic is known in advance, so asking
a model to classify it spends seconds learning nothing. When the message is
exactly one of these, the classifier is replaced by its known answer. The
match is on the text the server already holds -- no client flag is
trusted -- and anything else, including the same words typed with a typo,
goes through the normal classifier.

Keep in step with SUGGESTED_QUESTIONS in
frontend/components/chat/DecisionChat.tsx; a test checks they agree.
"""

PRESET_TOPICS: dict[str, str] = {
    "Explain the biggest difference": "broad",
    "Why will graduation take longer?": "timeline",
    "Break down the additional cost": "financial",
    "Compare the career outlook": "career",
    "What does this data not tell me?": "broad",
}


def preset_classifier(message: str):
    """A drop-in for classify_intent when `message` is a chip, else None."""
    topic = PRESET_TOPICS.get(message.strip())
    if topic is None:
        return None

    def classify(*_args, **_kwargs):
        from ai.interface import ConversationIntent

        return ConversationIntent(topic_scope=topic)

    return classify
