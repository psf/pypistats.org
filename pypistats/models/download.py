"""Package stats tables."""

from pypistats.database import Column
from pypistats.database import Model
from pypistats.extensions import db


class OverallDownloadCount(Model):
    """Overall download counts."""

    __tablename__ = "overall"

    date = Column(db.Date, primary_key=True, nullable=False)
    package = Column(db.String(128), primary_key=True, nullable=False, index=True)
    # with_mirrors or without_mirrors
    category = Column(db.String(16), primary_key=True, nullable=False)
    downloads = Column(db.BigInteger(), nullable=False)

    def __repr__(self):
        return "<OverallDownloadCount {}".format(f"{str(self.date)} - {str(self.package)} - {str(self.category)}")


class PythonMajorDownloadCount(Model):
    """Download counts by python major version."""

    __tablename__ = "python_major"

    date = Column(db.Date, primary_key=True, nullable=False)
    package = Column(db.String(128), primary_key=True, nullable=False, index=True)
    # python_major version, 2 or 3 (or null)
    category = Column(db.String(4), primary_key=True, nullable=True)
    downloads = Column(db.BigInteger(), nullable=False)

    def __repr__(self):
        return "<PythonMajorDownloadCount {}".format(f"{str(self.date)} - {str(self.package)} - {str(self.category)}")


class PythonMinorDownloadCount(Model):
    """Download counts by python minor version."""

    __tablename__ = "python_minor"

    date = Column(db.Date, primary_key=True)
    package = Column(db.String(128), primary_key=True, nullable=False, index=True)
    # python_minor version, e.g. 2.7 or 3.6 (or null)
    category = Column(db.String(4), primary_key=True, nullable=True)
    downloads = Column(db.BigInteger(), nullable=False)

    def __repr__(self):
        return "<PythonMinorDownloadCount {}".format(f"{str(self.date)} - {str(self.package)} - {str(self.category)}")


RECENT_CATEGORIES = ["day", "week", "month"]


class RecentDownloadCount(Model):
    """Recent day/week/month download counts."""

    __tablename__ = "recent"

    package = Column(db.String(128), primary_key=True, nullable=False, index=True)
    # recency, e.g. day, week, month
    category = Column(db.String(8), primary_key=True, nullable=False)
    downloads = Column(db.BigInteger(), nullable=False)

    def __repr__(self):
        return "<RecentDownloadCount {}>".format(f"{str(self.package)} - {str(self.category)}")


class SystemDownloadCount(Model):
    """Download counts by system."""

    __tablename__ = "system"

    date = Column(db.Date, primary_key=True)
    package = Column(db.String(128), primary_key=True, nullable=False, index=True)
    # system, e.g. Windows or Linux or Darwin (or null)
    category = Column(db.String(8), primary_key=True, nullable=True)
    downloads = Column(db.BigInteger(), nullable=False)

    def __repr__(self):
        return "<SystemDownloadCount {}".format(f"{str(self.date)} - {str(self.package)} - {str(self.category)}")
