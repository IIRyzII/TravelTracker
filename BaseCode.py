import sqlite3

connection = sqlite3.connect("Visited_Places.DB")
cursor = connection.cursor()

setup = """CREATE TABLE IF NOT EXISTS visited_countries(Location_name TEXT PRIMARY KEY)"""

cursor.execute(setup)

visited_cities = set()
visited_countries = set()
visited_continents = set()

# Load existing countries from database
cursor.execute("SELECT Location_name FROM visited_countries")
existing_countries = cursor.fetchall()
for country in existing_countries:
    visited_countries.add(country[0])

def addCountries(visited_countries):
    while True:
        newcountry = input("Please enter the country you visited: \n").strip()
        if newcountry == "":
            print("Please enter a real country: \n")
        elif newcountry in visited_countries:
            print("That country has already been visited, Please enter a new country: \n")
        else:
            visited_countries.add(newcountry)
            cursor.execute("INSERT INTO visited_countries (Location_name) VALUES (?)", (newcountry,))
            connection.commit()
            print(newcountry, "Has been added to your list")
            break

addCountries(visited_countries)

connection.close()

print(visited_countries)

