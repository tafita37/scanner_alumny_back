CREATE TABLE users(
   user_id SERIAL,
   name VARCHAR(50)  NOT NULL,
   first_name VARCHAR(50)  NOT NULL,
   email VARCHAR(50)  NOT NULL,
   password TEXT NOT NULL,
   PRIMARY KEY(user_id),
   UNIQUE(email)
);

CREATE TABLE tax_regime(
   tax_regime_id SERIAL,
   name VARCHAR(50)  NOT NULL,
   PRIMARY KEY(tax_regime_id),
   UNIQUE(name)
);

CREATE TABLE company_type(
   company_type_id SERIAL,
   name VARCHAR(50)  NOT NULL,
   PRIMARY KEY(company_type_id),
   UNIQUE(name)
);

CREATE TABLE ceo_info(
   ceo_info_id SERIAL,
   name VARCHAR(50)  NOT NULL,
   first_name VARCHAR(50)  NOT NULL,
   email VARCHAR(50)  NOT NULL,
   phone_number VARCHAR(50)  NOT NULL,
   job_title VARCHAR(50)  NOT NULL,
   PRIMARY KEY(ceo_info_id),
   UNIQUE(email),
   UNIQUE(phone_number)
);

CREATE TABLE city(
   city_id SERIAL,
   name VARCHAR(50)  NOT NULL,
   PRIMARY KEY(city_id),
   UNIQUE(name)
);

CREATE TABLE industry(
   industry_id SERIAL,
   name VARCHAR(50)  NOT NULL,
   PRIMARY KEY(industry_id),
   UNIQUE(name)
);

CREATE TABLE company(
   company_id SERIAL,
   siret_number VARCHAR(14)  NOT NULL,
   company_name VARCHAR(50)  NOT NULL,
   naf_code VARCHAR(5)  NOT NULL,
   creation_date DATE NOT NULL,
   city_id INTEGER NOT NULL,
   ceo_info_id INTEGER NOT NULL,
   company_type_id INTEGER NOT NULL,
   PRIMARY KEY(company_id),
   UNIQUE(siret_number),
   UNIQUE(company_name),
   FOREIGN KEY(city_id) REFERENCES city(city_id),
   FOREIGN KEY(ceo_info_id) REFERENCES ceo_info(ceo_info_id),
   FOREIGN KEY(company_type_id) REFERENCES company_type(company_type_id)
);

CREATE TABLE audit(
   audit_id SERIAL,
   head_count INTEGER NOT NULL,
   revenue NUMERIC(15,2)   NOT NULL,
   publciation_year INTEGER NOT NULL,
   average_deal_cost DOUBLE PRECISION NOT NULL,
   average_transaction_cost DOUBLE PRECISION NOT NULL,
   tax_regime_id INTEGER NOT NULL,
   company_id INTEGER NOT NULL,
   PRIMARY KEY(audit_id),
   FOREIGN KEY(tax_regime_id) REFERENCES tax_regime(tax_regime_id),
   FOREIGN KEY(company_id) REFERENCES company(company_id)
);

CREATE TABLE industry_company(
   industry_company_id SERIAL,
   company_id INTEGER NOT NULL,
   industry_id INTEGER NOT NULL,
   PRIMARY KEY(industry_company_id),
   FOREIGN KEY(company_id) REFERENCES company(company_id),
   FOREIGN KEY(industry_id) REFERENCES industry(industry_id)
);
