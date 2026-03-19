# engines/encounters/base.py
class EncounterContainer:
    def __init__(self, session):
        self.session = session
        self.is_active = True

    def handle_input(self, key):
        pass

    def render_overlay(self, screen, font):
        pass
