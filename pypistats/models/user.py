"""User tables."""

import datetime

from flask_login import UserMixin
from sqlalchemy.dialects.postgresql import ARRAY

from pypistats.database import Column
from pypistats.database import Model
from pypistats.database import SurrogatePK
from pypistats.extensions import db

MAX_FAVORITES = 20


class User(UserMixin, SurrogatePK, Model):
    """A user of the app."""

    __tablename__ = "users"

    uid = Column(db.Integer(), unique=True)
    username = Column(db.String(39), nullable=False)
    avatar_url = Column(db.String(256))
    token = Column(db.String(256))
    created_at = Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    active = Column(db.Boolean(), default=False)
    is_admin = Column(db.Boolean(), default=False)
    favorites = Column(ARRAY(db.String(128), dimensions=1))

    def __init__(self, token, **kwargs):
        """Create instance."""
        db.Model.__init__(self, token=token, **kwargs)

    def __repr__(self):
        """Represent instance as a unique string."""
        return f"<User({self.username})>"
