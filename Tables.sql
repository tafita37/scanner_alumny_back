CREATE TABLE users(
   id SERIAL,
   name VARCHAR(50)  NOT NULL,
   first_name VARCHAR(50)  NOT NULL,
   email VARCHAR(50)  NOT NULL,
   password TEXT NOT NULL,
   PRIMARY KEY(id),
   UNIQUE(email)
);

CREATE TABLE company_type(
   id SERIAL,
   label VARCHAR(200)  NOT NULL,
   label_level_1 VARCHAR(200)  NOT NULL,
   label_level_2 VARCHAR(200)  NOT NULL,
   code VARCHAR(4)  NOT NULL,
   PRIMARY KEY(id),
   UNIQUE(label),
   UNIQUE(code)
);

CREATE TABLE city(
   id SERIAL,
   name VARCHAR(50)  NOT NULL,
   code_insee VARCHAR(5)  NOT NULL,
   department_code VARCHAR(3)  NOT NULL,
   PRIMARY KEY(id),
   UNIQUE(code_insee)
);

CREATE TABLE city_postal_code(
   id SERIAL,
   postal_code VARCHAR(5)  NOT NULL,
   city_id INTEGER NOT NULL,
   PRIMARY KEY(id),
   FOREIGN KEY(city_id) REFERENCES city(id)
);

CREATE TABLE individual(
   id SERIAL,
   name VARCHAR(100)  NOT NULL,
   first_name VARCHAR(100)  NOT NULL,
   email VARCHAR(50)  NOT NULL,
   phone_number VARCHAR(50)  NOT NULL,
   PRIMARY KEY(id),
   UNIQUE(email),
   UNIQUE(phone_number)
);

CREATE TABLE ceo_info(
   id SERIAL,
   email VARCHAR(50)  NOT NULL,
   phone_number VARCHAR(50)  NOT NULL,
   job_title VARCHAR(50)  NOT NULL,
   individual_id INTEGER NOT NULL,
   PRIMARY KEY(id),
   FOREIGN KEY(individual_id) REFERENCES individual(id)
);

CREATE TABLE company(
   id SERIAL,
   siren_number VARCHAR(9)  NOT NULL,
   company_name VARCHAR(255)  NOT NULL,
   naf_code VARCHAR(6)  NOT NULL,
   creation_date DATE NOT NULL,
   city_id INTEGER NOT NULL,
   ceo_info_id INTEGER NOT NULL,
   company_type_id INTEGER NOT NULL,
   PRIMARY KEY(id),
   UNIQUE(siren_number),
   FOREIGN KEY(city_id) REFERENCES city(id),
   FOREIGN KEY(ceo_info_id) REFERENCES ceo_info(id),
   FOREIGN KEY(company_type_id) REFERENCES company_type(id)
);


CREATE TABLE tax_regime(
   id SERIAL,
   name VARCHAR(50)  NOT NULL,
   PRIMARY KEY(id),
   UNIQUE(name)
);

CREATE TABLE industry(
   id SERIAL,
   name VARCHAR(50)  NOT NULL,
   PRIMARY KEY(id),
   UNIQUE(name)
);

CREATE TABLE audit(
   id SERIAL,
   head_count INTEGER NOT NULL,
   revenue NUMERIC(15,2)   NOT NULL,
   publciation_year INTEGER NOT NULL,
   average_deal_cost DOUBLE PRECISION NOT NULL,
   average_transaction_cost DOUBLE PRECISION NOT NULL,
   siret_number VARCHAR(14)  NOT NULL,
   id_1 INTEGER NOT NULL,
   id_2 INTEGER NOT NULL,
   PRIMARY KEY(id),
   UNIQUE(siret_number),
   FOREIGN KEY(id_1) REFERENCES tax_regime(id),
   FOREIGN KEY(id_2) REFERENCES company(id)
);

CREATE TABLE industry_company(
   id SERIAL,
   id_1 INTEGER NOT NULL,
   id_2 INTEGER NOT NULL,
   PRIMARY KEY(id),
   FOREIGN KEY(id_1) REFERENCES company(id),
   FOREIGN KEY(id_2) REFERENCES industry(id)
);
