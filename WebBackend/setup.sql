-- FOR users.db --

CREATE TABLE "Users" (
    id integer PRIMARY KEY AUTOINCREMENT,
    name varchar(255),
    email varchar(255) UNIQUE,
    password_hash text NOT NULL
);

CREATE TABLE "Sessions" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token TEXT NOT NULL,
    start_time integer NOT NULL,
    duration integer NOT NULL,
    FOREIGN KEY (user_id) REFERENCES Users(id)
);

CREATE TABLE "User_sequences" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    hla_la TEXT DEFAULT NULL,
    optitype TEXT DEFAULT NULL,
    hisat_genotype TEXT DEFAULT NULL,
    snp_bridge TEXT DEFAULT NULL,
    FOREIGN KEY (user_id) REFERENCES Users(id)
);