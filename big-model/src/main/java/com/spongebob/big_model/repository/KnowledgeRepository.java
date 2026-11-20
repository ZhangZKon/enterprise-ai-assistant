package com.spongebob.big_model.repository;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;

import com.spongebob.big_model.entity.KnowledgeBase;
import com.spongebob.big_model.mapper.KnowledgeBaseMapper;
import org.springframework.stereotype.Repository;

@Repository
public class KnowledgeRepository extends ServiceImpl<KnowledgeBaseMapper, KnowledgeBase>{

}
