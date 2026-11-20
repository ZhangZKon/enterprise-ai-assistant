package com.spongebob.big_model;


import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.ComponentScan;

@SpringBootApplication
@ComponentScan(basePackages = {"com.spongebob.big_model.*"})
public class MagicConchBackendApplication {

    public static void main(String[] args) {
        SpringApplication.run(MagicConchBackendApplication.class, args);
    }

}
