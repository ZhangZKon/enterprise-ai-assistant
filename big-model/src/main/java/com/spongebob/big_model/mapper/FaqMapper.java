package com.spongebob.big_model.mapper;


import com.baomidou.mybatisplus.extension.spring.MybatisSqlSessionFactoryBean;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;

import com.spongebob.big_model.entity.Faq;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface FaqMapper extends BaseMapper<Faq> {
}
