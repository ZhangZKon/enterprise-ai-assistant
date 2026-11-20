package com.spongebob.big_model.repository;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;

import com.spongebob.big_model.entity.QaRecord;
import com.spongebob.big_model.mapper.QaRecordMapper;
import org.springframework.stereotype.Repository;

@Repository
public class QaRecordRepository extends ServiceImpl<QaRecordMapper, QaRecord> {

}
