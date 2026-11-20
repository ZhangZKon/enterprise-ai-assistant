package com.spongebob.big_model.repository;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.spongebob.big_model.entity.SysUser;
import com.spongebob.big_model.mapper.SysUserMapper;
import org.springframework.stereotype.Repository;

@Repository
public class SysUserRepository extends ServiceImpl<SysUserMapper, SysUser> {

}
