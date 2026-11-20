package com.spongebob.big_model.repository;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.spongebob.big_model.entity.Faq;
import com.spongebob.big_model.mapper.FaqMapper;
import org.springframework.stereotype.Repository;

@Repository
public class FaqRepository extends ServiceImpl<FaqMapper, Faq> {
}
