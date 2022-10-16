# -*- coding: utf-8 -*-
# @Time    : 2022/10/8
# @Author  : Naihe
# @Email   : 239144498@qq.com
# @File    : sgtv.py
# @Software: PyCharm
import asyncio

import aiohttp
from fastapi import APIRouter, Query, Response
from loguru import logger
from fastapi.background import BackgroundTasks
from fastapi.responses import StreamingResponse, RedirectResponse

from app.api.a4gtv.tools import generate_m3u, now_time
from app.api.a4gtv.utile import get, backtaskonline, backtasklocal
from app.common.header import random_header
from app.conf.config import default_cfg, idata, localhost, host2, host1, headers
from app.db.DBtools import DBconnect
from app.scheams.basic import Response200, Response400

sgtv = APIRouter(tags=["4GTV"])


@sgtv.get('/online.m3u8', summary="带缓冲区m3u8")
async def online(
        background_tasks: BackgroundTasks,
        host=Query(localhost),
        fid=Query(...),
        hd=Query("1080")):
    """
    最新版 api v3
    该版本具有redis缓存，视频中转缓存处理等优点,直白说就是播放稳定不卡顿，看超清、4k不是问题
    """
    if default_cfg['defaultdb'] == "":
        return Response200(msg="此功能禁用，请连接数据库")
    if not (fid in idata):
        return Response400(data=f"Not found {fid}", code=404)
    t = idata[fid].get("lt", 0) - now_time()
    if t > 0:
        return Response400(data=f"{fid} 频道暂不可用，请过 {t} 秒后重试", code=405)
    code = await get.check(fid)
    if code != 200:
        return Response400(data=f"{fid} 频道暂不可用，请过 {idata[fid].get('lt', 0) - now_time()} 秒后重试", code=406)
    return StreamingResponse(get.new_generatem3u8(host, fid, hd, background_tasks), 200,
                             media_type="application/vnd.apple.mpegurl")


@sgtv.get('/channel.m3u8', summary="代理|转发m3u8")
async def channel1(
        host=Query(localhost),
        fid=Query(...),
        hd=Query("720")):
    """
    新版优化api v3
    在redis中设置截止时间，过期重新获取保存到redis，默认通过读取redis参数，构造ts链接
    新增对接口复用，channel2接口重定向到该接口做转发，默认采取代理方式
    """
    if not (fid in idata):
        return Response400(data=f"Not found {fid}", code=404)
    t = idata[fid].get("lt", 0) - now_time()
    if t > 0:
        return Response400(data=f"{fid} 频道暂不可用，请过 {t} 秒后重试", code=405)
    code = await get.check(fid)  # 檢查是否出错
    if code != 200:
        return Response400(data=f"{fid} 频道暂不可用，请过 {idata[fid].get('lt', 0) - now_time()} 秒后重试", code=406)
    return StreamingResponse(get.generatem3u8(host or "239144498@qq.com", fid, hd), 200, media_type="application/vnd.apple.mpegurl")


@sgtv.get('/channel2.m3u8', summary="重定向m3u8")
async def channel2(
        host=Query(None),
        fid=Query(...),
        hd=Query("720")):
    """
    新版优化api v2
    读取redis获取链接进行重定向
    """
    if not (fid in idata):
        return Response400(data=f"Not found {fid}", code=404)
    t = idata[fid].get("lt", 0) - now_time()
    if t > 0:  # 冷卻期
        return Response400(data=f"{fid} 频道暂不可用，请过 {t} 秒后重试", code=405)
    code = await get.check(fid)  # 檢查是否出错
    if code != 200:
        return Response400(data=f"{fid} 频道暂不可用，请过 {idata[fid].get('lt', 0) - now_time()} 秒后重试", code=406)
    host = host or host2 if "4gtv-live" in fid else host1
    return RedirectResponse(f"channel.m3u8?fid={fid}&hd={hd}&host={host}", status_code=307)


@sgtv.get('/program.m3u', summary="IPTV频道列表")
async def program(
        host=Query(localhost),
        hd=Query("720"),
        name="channel2"):
    """
    生成频道表，由程序生成数据
    """
    name += ".m3u8"
    return StreamingResponse(generate_m3u(host, hd, name), 200, media_type="application/vnd.apple.mpegurl")


@sgtv.get('/epg.xml', summary="IPTV节目预告")
def epg():
    """
    获取4gtv未来3天所有节目表
    """
    return RedirectResponse("https://agit.ai/239144498/demo/raw/branch/master/4gtvchannel.xml", status_code=302)


@sgtv.get('/call.ts', summary="缓存式ts视频下载")
async def call(background_tasks: BackgroundTasks, fid: str, seq: str, hd: str):
    """
    api v3 版中读取数据库ts片响应给客户端，采用多线程下载ts片，加载视频没有等待时长！
    """
    if default_cfg['defaultdb'] == "":
        return Response200(msg="此功能禁用，请连接数据库")
    logger.info(f"{fid} {seq}")
    if not (fid in idata):
        return Response200(msg="NOT FOUND " + fid)
    vname = fid + str(seq) + ".ts"
    gap, seq, url, begin = get.generalfun(fid, hd)
    if default_cfg.get("downchoose") == "online":
        background_tasks.add_task(backtaskonline, url, fid, seq, hd, begin, None)
    elif default_cfg.get("downchoose") == "local":
        background_tasks.add_task(backtasklocal, url, fid, seq, hd, begin, None)
    for i in range(1, 10):
        logger.info(f"第{i}次尝试获取{get.filename.get(vname)}")
        if get.filename.get(vname) and get.filename.get(vname) != 0:
            sql = "SELECT vcontent FROM video where vname='{}'".format(vname)
            content = DBconnect.fetchone(sql)
            return Response(content=content['vcontent'], status_code=200, headers=headers)
        else:
            await asyncio.sleep(1 + i * 0.095)
    return Response400(msg="NOT FOUND " + vname)


@sgtv.get("/live/{file_path:path}", summary="代理ts视频下载")
async def downlive(file_path: str, token1: str = None, expires1: int = None):
    """
    api v2 版代理请求，客户端无需翻墙即可观看海外电视
    """
    file_path = "/live/" + file_path
    if "live/pool/" not in file_path:
        return Response400(msg="wrong parameter")
    if token1 and expires1:
        file_path += f"?token1={token1}&expires1={expires1}"
    url = host2 + file_path if "live/pool/4gtv-live" in file_path else host1 + file_path
    header = {
        "User-Agent": random_header(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2",
        "Accept-Encoding": "gzip, deflate, br",
        "Upgrade-Insecure-Requests": "1",
    }
    async with aiohttp.ClientSession(headers=header) as session:
        async with session.get(url=url) as res:
            if res.status != 200:
                logger.warning(await res.text())
                return Response400(msg="Error in requestr")
            return Response(content=await res.read(), status_code=200, headers=headers, media_type='video/MP2T')