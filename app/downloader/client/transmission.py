import os.path
from datetime import datetime

import transmission_rpc

import log
from config import Config
from app.downloader.client.client import IDownloadClient


class Transmission(IDownloadClient):
    # 参考transmission web，仅查询需要的参数，加速种子检索
    __trarg = ["id", "name", "status", "labels", "hashString", "totalSize", "percentDone", "addedDate", "trackerStats",
               "leftUntilDone", "rateDownload", "rateUpload", "recheckProgress", "rateDownload", "rateUpload",
               "peersGettingFromUs", "peersSendingToUs", "uploadRatio", "uploadedEver", "downloadedEver", "downloadDir",
               "error", "errorString", "doneDate", "queuePosition", "activityDate"]
    trc = None

    def get_config(self):
        # 读取配置文件
        config = Config()
        transmission = config.get_config('transmission')
        if transmission:
            self.host = transmission.get('trhost')
            self.port = int(transmission.get('trport')) if str(transmission.get('trport')).isdigit() else 0
            self.username = transmission.get('trusername')
            self.password = transmission.get('trpassword')

    def connect(self):
        if self.host and self.port:
            self.trc = self.__login_transmission()

    def __login_transmission(self):
        """
        连接transmission
        :return: transmission对象
        """
        try:
            # 登录
            trt = transmission_rpc.Client(host=self.host,
                                          port=self.port,
                                          username=self.username,
                                          password=self.password,
                                          timeout=10)
            return trt
        except Exception as err:
            log.error("【TR】transmission连接出错：%s" % str(err))
            return None

    def get_status(self):
        return True if self.trc else False

    def get_torrents(self, ids=None, status=None, tag=None):
        if not self.trc:
            return []
        if isinstance(ids, list):
            ids = [int(x) for x in ids if str(x).isdigit()]
        elif str(ids).isdigit():
            ids = int(ids)
        try:
            torrents = self.trc.get_torrents(ids=ids, arguments=self.__trarg)
        except Exception as err:
            print(str(err))
            return []
        if status and not isinstance(status, list):
            status = [status]
        ret_torrents = []
        for torrent in torrents:
            if status and torrent.status not in status:
                continue
            labels = torrent.labels if hasattr(torrent, "labels") else []
            if tag and tag not in labels:
                continue
            ret_torrents.append(torrent)
        return ret_torrents

    def get_completed_torrents(self, tag=None):
        if not self.trc:
            return []
        try:
            return self.get_torrents(status=["seeding", "seed_pending"], tag=tag)
        except Exception as err:
            print(str(err))
            return []

    def get_downloading_torrents(self, tag=None):
        if not self.trc:
            return []
        return self.get_torrents(status=["downloading", "download_pending", "stopped"], tag=tag)

    def set_torrents_status(self, ids):
        if not self.trc:
            return
        if isinstance(ids, list):
            ids = [int(x) for x in ids if str(x).isdigit()]
        elif str(ids).isdigit():
            ids = int(ids)
        # 打标签
        try:
            self.trc.change_torrent(labels=["已整理"], ids=ids)
            log.info("【TR】设置transmission种子标签成功")
        except Exception as err:
            print(str(err))

    def set_torrent_tag(self, tid, tag):
        if not tid or not tag:
            return
        try:
            self.trc.change_torrent(labels=tag, ids=int(tid))
        except Exception as err:
            print(str(err))

    def change_torrent(self,
                       tid,
                       tag=None,
                       upload_limit=None,
                       download_limit=None,
                       ratio_limit=None,
                       seeding_time_limit=None):
        """
        设置种子
        :param tid: ID
        :param tag: 标签
        :param upload_limit: 上传限速 Mb/s
        :param download_limit: 下载限速 Mb/s
        :param ratio_limit: 分享率限制
        :param seeding_time_limit: 做种时间限制
        :return: bool
        """
        if not tid:
            return
        else:
            ids = int(tid)
        if tag:
            if isinstance(tag, list):
                labels = tag
            else:
                labels = [tag]
        else:
            labels = []
        if upload_limit:
            uploadLimited = True
            uploadLimit = int(upload_limit)
        else:
            uploadLimited = False
            uploadLimit = None
        if download_limit:
            downloadLimited = True
            downloadLimit = int(download_limit)
        else:
            downloadLimited = False
            downloadLimit = None
        if ratio_limit:
            seedRatioMode = 1
            seedRatioLimit = round(float(ratio_limit), 2)
        else:
            seedRatioMode = 2
            seedRatioLimit = None
        if seeding_time_limit:
            seedIdleMode = 1
            seedIdleLimit = int(seeding_time_limit)
        else:
            seedIdleMode = 2
            seedIdleLimit = None
        try:
            self.trc.change_torrent(ids=ids,
                                    labels=labels,
                                    uploadLimited=uploadLimited,
                                    uploadLimit=uploadLimit,
                                    downloadLimited=downloadLimited,
                                    downloadLimit=downloadLimit,
                                    seedRatioMode=seedRatioMode,
                                    seedRatioLimit=seedRatioLimit,
                                    seedIdleMode=seedIdleMode,
                                    seedIdleLimit=seedIdleLimit)
        except Exception as err:
            print(str(err))

    def get_transfer_task(self, tag):
        # 处理所有任务
        torrents = self.get_completed_torrents(tag=tag)
        trans_tasks = []
        for torrent in torrents:
            # 3.0版本以下的Transmission没有labels
            if not hasattr(torrent, "labels"):
                log.error(f"【TR】当前transmission版本可能过低，无labels属性，请安装3.0以上版本！")
                break
            if torrent.labels and "已整理" in torrent.labels:
                continue
            path = torrent.download_dir
            if not path:
                continue
            true_path = self.get_replace_path(path)
            trans_tasks.append({'path': os.path.join(true_path, torrent.name), 'id': torrent.id})
        return trans_tasks

    def get_remove_torrents(self, seeding_time, tag):
        if not seeding_time:
            return []
        torrents = self.get_completed_torrents(tag=tag)
        remove_torrents = []
        for torrent in torrents:
            date_done = torrent.date_done
            if not date_done:
                date_done = torrent.date_added
            if not date_done:
                continue
            date_now = datetime.now().astimezone()
            torrent_time = (date_now - date_done).seconds
            if torrent_time > int(seeding_time):
                log.info("【TR】%s 做种时间：%s（秒），已达清理条件，进行清理..." % (torrent.name, torrent_time))
                remove_torrents.append(torrent.id)
        return remove_torrents

    def add_torrent(self, content,
                    is_paused=False,
                    download_dir=None,
                    upload_limit=None,
                    download_limit=None,
                    **kwargs):
        try:
            ret = self.trc.add_torrent(torrent=content,
                                       download_dir=download_dir,
                                       paused=is_paused)
            if ret and ret.id:
                if upload_limit:
                    self.set_uploadspeed_limit(ret.id, int(upload_limit))
                if download_limit:
                    self.set_downloadspeed_limit(ret.id, int(download_limit))
            return ret
        except Exception as err:
            print(str(err))
            return False

    def start_torrents(self, ids):
        if not self.trc:
            return False
        if isinstance(ids, list):
            ids = [int(x) for x in ids if str(x).isdigit()]
        elif str(ids).isdigit():
            ids = int(ids)
        try:
            return self.trc.start_torrent(ids=ids)
        except Exception as err:
            print(str(err))
            return False

    def stop_torrents(self, ids):
        if not self.trc:
            return False
        if isinstance(ids, list):
            ids = [int(x) for x in ids if str(x).isdigit()]
        elif str(ids).isdigit():
            ids = int(ids)
        try:
            return self.trc.stop_torrent(ids=ids)
        except Exception as err:
            print(str(err))
            return False

    def delete_torrents(self, delete_file, ids):
        if not self.trc:
            return False
        if not ids:
            return False
        if isinstance(ids, list):
            ids = [int(x) for x in ids if str(x).isdigit()]
        elif str(ids).isdigit():
            ids = int(ids)
        try:
            return self.trc.remove_torrent(delete_data=delete_file, ids=ids)
        except Exception as err:
            print(str(err))
            return False

    def get_files(self, tid):
        """
        获取种子文件列表
        """
        if not tid:
            return None
        try:
            torrent = self.trc.get_torrent(tid)
        except Exception as err:
            print(str(err))
            return None
        if torrent:
            return torrent.files()
        else:
            return None

    def set_files(self, **kwargs):
        """
        设置下载文件的状态
        {
            <torrent id>: {
                <file id>: {
                    'priority': <priority ('high'|'normal'|'low')>,
                    'selected': <selected for download (True|False)>
                },
                ...
            },
            ...
        }
        """
        if not kwargs.get("file_info"):
            return False
        try:
            self.trc.set_files(kwargs.get("file_info"))
            return True
        except Exception as err:
            print(str(err))
            return False

    def get_download_dirs(self):
        if not self.trc:
            return []
        try:
            return [self.trc.get_session(timeout=5).download_dir]
        except Exception as err:
            print(str(err))
            return []

    def set_uploadspeed_limit(self, ids, limit):
        """
        设置上传限速，单位 KB/sec
        """
        if not self.trc:
            return
        if not ids or not limit:
            return
        if not isinstance(ids, list):
            ids = int(ids)
        else:
            ids = [int(x) for x in ids if str(x).isdigit()]
        self.trc.change_torrent(ids, uploadLimit=int(limit))

    def set_downloadspeed_limit(self, ids, limit):
        """
        设置下载限速，单位 KB/sec
        """
        if not self.trc:
            return
        if not ids or not limit:
            return
        if not isinstance(ids, list):
            ids = int(ids)
        else:
            ids = [int(x) for x in ids if str(x).isdigit()]
        self.trc.change_torrent(ids, downloadLimit=int(limit))
