"""JSON API routes."""

from flask import Blueprint
from flask import abort
from flask import g
from flask import jsonify
from flask import render_template
from flask import request

from pypistats.models.download import RECENT_CATEGORIES
from pypistats.models.download import OverallDownloadCount
from pypistats.models.download import PythonMajorDownloadCount
from pypistats.models.download import PythonMinorDownloadCount
from pypistats.models.download import RecentDownloadCount
from pypistats.models.download import SystemDownloadCount

blueprint = Blueprint("api", __name__, url_prefix="/api")


@blueprint.route("/")
def api():
    """Get API documentation."""
    return render_template("api.html", user=g.user)


@blueprint.route("/packages/<package>/recent")
def api_downloads_recent(package):
    """Get the recent downloads of a package."""
    # abort(503)
    if package != "__all__":
        package = package.replace(".", "-").replace("_", "-")
    category = request.args.get("period")
    if category is None:
        downloads = RecentDownloadCount.query.filter_by(package=package).all()
    elif category in RECENT_CATEGORIES:
        downloads = RecentDownloadCount.query.filter_by(package=package, category=category).all()
    else:
        abort(404)

    response = {"package": package, "type": "recent_downloads"}
    if len(downloads) > 0:
        if category is None:
            response["data"] = {"last_" + rc: 0 for rc in RECENT_CATEGORIES}
        else:
            response["data"] = {"last_" + category: 0}
        for r in downloads:
            response["data"]["last_" + r.category] = r.downloads
    else:
        abort(404)

    return jsonify(response)


@blueprint.route("/packages/<package>/overall")
def api_downloads_overall(package):
    """Get the overall download time series of a package."""
    # abort(503)
    if package != "__all__":
        package = package.replace(".", "-").replace("_", "-")
    mirrors = request.args.get("mirrors")
    if mirrors == "true":
        downloads = (
            OverallDownloadCount.query.filter_by(package=package, category="with_mirrors")
            .order_by(OverallDownloadCount.date)
            .all()
        )
    elif mirrors == "false":
        downloads = (
            OverallDownloadCount.query.filter_by(package=package, category="without_mirrors")
            .order_by(OverallDownloadCount.date)
            .all()
        )
    else:
        downloads = (
            OverallDownloadCount.query.filter_by(package=package)
            .order_by(OverallDownloadCount.category, OverallDownloadCount.date)
            .all()
        )

    response = {"package": package, "type": "overall_downloads"}
    if len(downloads) > 0:
        response["data"] = [{"date": str(r.date), "category": r.category, "downloads": r.downloads} for r in downloads]
    else:
        abort(404)

    return jsonify(response)


@blueprint.route("/packages/<package>/python_major")
def api_downloads_python_major(package):
    """Get the python major download time series of a package."""
    return generic_downloads(PythonMajorDownloadCount, package, "version", "python_major")


@blueprint.route("/packages/<package>/python_minor")
def api_downloads_python_minor(package):
    """Get the python minor download time series of a package."""
    return generic_downloads(PythonMinorDownloadCount, package, "version", "python_minor")


@blueprint.route("/packages/<package>/system")
def api_downloads_system(package):
    """Get the system download time series of a package."""
    return generic_downloads(SystemDownloadCount, package, "os", "system")


def generic_downloads(model, package, arg, name):
    """Generate a generic response."""
    # abort(503)
    if package != "__all__":
        package = package.replace(".", "-").replace("_", "-")
    category = request.args.get(arg)
    if category is not None:
        downloads = model.query.filter_by(package=package, category=category.title()).order_by(model.date).all()
    else:
        downloads = model.query.filter_by(package=package).order_by(model.category, model.date).all()

    response = {"package": package, "type": f"{name}_downloads"}
    if downloads is not None:
        response["data"] = [{"date": str(r.date), "category": r.category, "downloads": r.downloads} for r in downloads]
    else:
        abort(404)

    return jsonify(response)


# TODO
# @blueprint.route("/top/overall")
# def api_top_packages():
#     """Get the most downloaded packages by recency."""
#     return "top overall"
#
#
# @blueprint.route("/top/python_major")
# def api_top_python_major():
#     """Get the most downloaded packages by python major version."""
#     return "top python_major"
#
#
# @blueprint.route("/top/python_minor")
# def api_top_python_minor():
#     """Get the most downloaded packages by python minor version."""
#     return "top python_minor"
#
#
# @blueprint.route("/top/system")
# def api_top_system():
#     """Get the most downloaded packages by system."""
#     return "top python_minor"
