import os
import requests

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_session import Session
from tempfile import mkdtemp
from requests import api
from sqlalchemy.sql.expression import null
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True


# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")

API_KEY = os.environ.get("API_KEY")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""

    # Get from db all stocks from user
    tlist = db.execute(
        "SELECT symbol, SUM(shares), stock_name FROM stocks WHERE user_id = ?  GROUP BY symbol;", session["user_id"]
    )

    if len(tlist) == 0:
        totalcash = 0
        usercash = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])
        totalcash = totalcash + usercash[0]["cash"]
        return render_template("portfolio.html", tlist=tlist, usercash=usercash[0]["cash"], totalcash=totalcash)

    symbolsList = []
    for i, t in enumerate(tlist):
        if t["SUM(shares)"] <= 0:
            print("removed")
            print(t)
            del tlist[i]

    for s in tlist:
        symbolsList.append(s["symbol"])
    stringSymbols = ",".join(symbolsList)

    # define all symbols to requesto into the API
    api_url = (
        f"https://cloud.iexapis.com/stable/stock/market/batch?symbols={stringSymbols}&types=quote&token={API_KEY}"
    )
    if requests.get(api_url).status_code != 200:
        return apology("Unexpected Error")
    stock = requests.get(api_url).json()

    # Insert the correct price values, tries Real time if not avaiable get latest price
    for t in tlist:
        t["shares"] = t.pop("SUM(shares)")

        price = stock[t["symbol"]]["quote"]["iexRealtimePrice"]
        if price == None:
            price = stock[t["symbol"]]["quote"]["latestPrice"]
        t["actualprice"] = price

        # Give the total money (Cash and Shares)
        totalcash = 0
        t["total"] = t["actualprice"] * float(t["shares"])
        totalcash += t["total"]

    usercash = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])
    totalcash = totalcash + usercash[0]["cash"]

    return render_template("portfolio.html", tlist=tlist, usercash=usercash[0]["cash"], totalcash=totalcash)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "POST":
        # request API stock and cached
        symbol = request.form.get("symbol")
        api_url = f"https://cloud.iexapis.com/stable/stock/{symbol}/quote?token={API_KEY}"
        if requests.get(api_url).status_code != 200:
            return apology("Not valid input")
        stock = requests.get(api_url).json()
        price = stock["iexRealtimePrice"]
        if stock["iexRealtimePrice"] == None:
            price = stock["latestPrice"]

        # check if have money enough
        walletcash = db.execute("SELECT cash FROM users WHERE id = ?;", session["user_id"])
        sharesqnt = request.form.get("shares")
        if walletcash[0]["cash"] < float(price) * float(sharesqnt):
            return apology("Not enought money", 406)

        # add bought shares to user wallet
        db.execute(
            "INSERT INTO stocks (user_id, symbol, stock_name, shares, priceatbuy) VALUES (?, ?, ?, ?, ?)",
            session["user_id"],
            stock["symbol"],
            stock["companyName"],
            sharesqnt,
            price,
        )

        # Update cash after buy
        db.execute("UPDATE users SET cash = ? WHERE id = ?", (walletcash[0]["cash"]) - price, session["user_id"])

        flash("Bought!")
        return redirect("/")

    return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    tlist = db.execute(
        "SELECT symbol, shares, priceatbuy, ts, dt FROM stocks WHERE user_id = ? ORDER BY id_stock DESC;",
        session["user_id"],
    )
    size = len(tlist)

    return render_template("history.html", tlist=tlist, size=size)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]
        name = rows[0]["username"]
        session["username"] = name[0].upper() + name[1:]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "POST":
        symbol = request.form.get("symbol")
        api_url = f"https://cloud.iexapis.com/stable/stock/{symbol}/quote?token={API_KEY}"
        if requests.get(api_url).status_code != 200:
            return apology("Not valid input")
        stock = requests.get(api_url).json()
        price = stock["iexRealtimePrice"]
        if stock["iexRealtimePrice"] == None:
            price = stock["latestPrice"]

        return render_template("quoted.html", data=stock, price=price)

    # Get first top 5 stocks and pass de list to render_template
    topstocks = ["AAPL", "AMZN", "GOOGL", "NFLX", "msft"]
    stringStocks = ",".join(topstocks)
    stocks = []

    api_url = f"https://cloud.iexapis.com/stable/stock/market/batch?symbols={stringStocks}&types=quote&token={API_KEY}"
    if requests.get(api_url).status_code != 200:
        return apology("Unexpected Error")
    stocks = requests.get(api_url).json()

    return render_template("quote.html", stocks=stocks)


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "POST":
        name = request.form.get("username").lower()
        passwd = request.form.get("password")
        repetedPasswd = request.form.get("repeatpassword")
        phash = generate_password_hash(passwd, method="pbkdf2:sha256", salt_length=8)

        if not (check_password_hash(phash, passwd)) or passwd != repetedPasswd:
            return apology("The passwords don't match", 406)

        # check if user already exist, if not add to db
        if len(db.execute("SELECT username FROM users WHERE username = ?", name)) == 0:
            db.execute("INSERT INTO users(username, hash) VALUES (?, ?)", name, phash)
            print("================= user added to db! ======================")
        else:
            return "User Exist"

        # flask.redirect(flask.url_for('operation'))
        return redirect(url_for("login"), code=307)
    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    if request.method == "POST":
        symName = request.form.get("symbol")
        sharesqtn = request.form.get("shares")

        # TODO check if user have the number o shares select to sell
        # TODO check if user have the number o shares select to sell
        # TODO check if user have the number o shares select to sell

        # Get the actual price
        api_url = f"https://cloud.iexapis.com/stable/stock/{symName}/quote?token={API_KEY}"
        stock = requests.get(api_url).json()
        price = stock["iexRealtimePrice"]
        if stock["iexRealtimePrice"] == None:
            price = stock["latestPrice"]

        # Stamp the sell transaction into db
        db.execute(
            "INSERT INTO stocks (user_id, symbol, shares, priceatbuy) VALUES (?, ?, ?, ?)",
            session["user_id"],
            symName,
            0 - int(sharesqtn),
            price,
        )

        # Update user cash wallet
        walletcash = db.execute("SELECT cash FROM users WHERE id = ?;", session["user_id"])

        db.execute("UPDATE users SET cash = ? WHERE id = ?;", float(walletcash[0]["cash"]) + price, session["user_id"])

        flash("Sold!")
        return redirect("/")

    list = db.execute("SELECT DISTINCT(symbol) FROM stocks WHERE user_id = ?;", session["user_id"])
    size = len(list)

    return render_template("sell.html", list=list)


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
