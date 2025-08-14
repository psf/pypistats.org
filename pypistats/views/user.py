"""User page for tracking packages."""

from flask import Blueprint
from flask import abort
from flask import flash
from flask import g
from flask import redirect
from flask import render_template
from flask import request
from flask import session
from flask import url_for

from pypistats.extensions import github
from pypistats.models.download import RecentDownloadCount
from pypistats.models.user import MAX_FAVORITES
from pypistats.models.user import User

blueprint = Blueprint("user", __name__, template_folder="templates")


@github.access_token_getter
def token_getter():
    """Get the token for a user."""
    this_user = g.user
    if this_user is not None:
        return this_user.token


@blueprint.route("/github-callback")
@github.authorized_handler
def authorized(oauth_token):
    """Github authorization callback."""
    next_url = request.args.get("next") or url_for("user.user")
    if oauth_token is None:
        flash("Authorization failed.")
        return redirect(next_url)

    # Ensure a user with token doesn't already exist
    this_user = User.query.filter_by(token=oauth_token).first()
    if this_user is None:
        this_user = User(token=oauth_token)

    # Set this to use API to get user data
    g.user = this_user
    user_data = github.get("user")

    # extract data
    uid = user_data["id"]
    username = user_data["login"]
    avatar_url = user_data["avatar_url"]

    # Create/update the user
    this_user = User.query.filter_by(uid=uid).first()
    if this_user is None:
        this_user = User(token=oauth_token, uid=uid, username=username, avatar_url=avatar_url)
    else:
        this_user.username = username
        this_user.avatar_url = avatar_url
        this_user.token = oauth_token

    this_user.save()

    session["username"] = this_user.username
    session["user_id"] = this_user.id
    g.user = this_user

    return redirect(next_url)


@blueprint.route("/login")
def login():
    """Login via GitHub OAuth."""
    if session.get("user_id", None) is None:
        return github.authorize()
    else:
        return redirect(url_for("user.user"))


@blueprint.route("/logout")
def logout():
    """Logout."""
    session.pop("user_id", None)
    session.pop("username", None)
    g.user = None
    return redirect(url_for("general.index"))


@blueprint.route("/user")
def user():
    """Render the user's personal page."""
    return render_template("user.html", user=g.user)


@blueprint.route("/user/packages/<package>")
def user_package(package):
    """Handle adding and deleting packages to user's list."""
    if g.user:
        # Ensure package is valid.
        downloads = RecentDownloadCount.query.filter_by(package=package).all()

        # Handle add/remove to favorites
        if g.user.favorites is None:
            # Ensure package is valid before adding
            if len(downloads) == 0:
                return abort(400)
            g.user.favorites = [package]
            g.user.update()
            return redirect(url_for("user.user"))
        elif package in g.user.favorites:
            favorites = g.user.favorites
            favorites.remove(package)
            # Workaround for sqlalchemy mutable ARRAY types
            g.user.favorites = None
            g.user.save()
            g.user.favorites = favorites
            g.user.save()
            return redirect(url_for("user.user"))
        else:
            if len(g.user.favorites) < MAX_FAVORITES:
                # Ensure package is valid before adding
                if len(downloads) == 0:
                    return abort(400)
                favorites = g.user.favorites
                favorites.append(package)
                favorites = sorted(favorites)
                # Workaround for sqlalchemy mutable ARRAY types
                g.user.favorites = None
                g.user.save()
                g.user.favorites = favorites
                g.user.save()
                return redirect(url_for("user.user"))
            else:
                return f"Maximum package number reached ({MAX_FAVORITES})."
    return abort(400)
