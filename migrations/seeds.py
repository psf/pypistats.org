import datetime
import logging
import random
import subprocess
import sys

from pypistats.application import create_app
from pypistats.application import db
from pypistats.models.download import OverallDownloadCount
from pypistats.models.download import PythonMajorDownloadCount
from pypistats.models.download import PythonMinorDownloadCount
from pypistats.models.download import RecentDownloadCount
from pypistats.models.download import SystemDownloadCount

# required to use the db models outside of the context of the app
app = create_app()
app.app_context().push()

if db.session.query(RecentDownloadCount.package).count() > 0:
    print("Seeds already exist.")
    sys.exit(0)

# use the currently installed dependencies as seed packages
result = subprocess.run(["pip", "list", "--format=freeze"], stdout=subprocess.PIPE)
output = result.stdout.decode()

# extract just the package names from the output
packages = []
for line in output.split("\n"):
    if "==" in line:
        packages.append(line.split("==")[0])

# add some packages that have optional dependencies
packages.append("apache-airflow")
packages.append("databricks-dbapi")

logging.info(packages)

# take the last 120 days
end_date = datetime.date.today()
date_list = [end_date - datetime.timedelta(days=x) for x in range(120)][::-1]

baseline = 1000

# build a bunch of seed records with random values
records = []
for package in packages + ["__all__"]:
    print("Seeding: " + package)

    for idx, category in enumerate(["day", "week", "month"]):
        record = RecentDownloadCount(
            package=package, category=category, downloads=baseline * (idx + 1) + random.randint(-100, 100)
        )
        records.append(record)

    for date in date_list:
        for idx, category in enumerate(["with_mirrors", "without_mirrors"]):
            record = OverallDownloadCount(
                date=date,
                package=package,
                category=category,
                downloads=baseline * (idx + 1) + random.randint(-100, 100),
            )
            records.append(record)

        for idx, category in enumerate(["null", "2", "3"]):
            record = PythonMajorDownloadCount(
                date=date,
                package=package,
                category=category,
                downloads=baseline * (idx + 1) + random.randint(-100, 100),
            )
            records.append(record)

        for idx, category in enumerate(
            ["null", "2.7", "3.4", "3.5", "3.6", "3.7", "3.8", "3.9", "3.10", "3.11", "3.12"]
        ):
            record = PythonMinorDownloadCount(
                date=date,
                package=package,
                category=category,
                downloads=baseline * (idx + 1) + random.randint(-100, 100),
            )
            records.append(record)

        for idx, category in enumerate(["null", "windows", "linux", "darwin"]):
            record = SystemDownloadCount(
                date=date,
                package=package,
                category=category,
                downloads=baseline * (idx + 1) + random.randint(-100, 100),
            )
            records.append(record)

# push to the local database
db.session.bulk_save_objects(records)
db.session.commit()
