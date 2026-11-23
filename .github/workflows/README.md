# GitHub Actions 已停用

本目录下的 workflow 已重命名为 `.yml.disabled`，GitHub 不会执行：

- `daily.yml.disabled`：曾用于每日 PubMed 更新，现由本地 `metaweb.py publish` 代替
- `visitors.yml.disabled`：曾用于从服务器拉取 nginx 日志生成访客地图

恢复方式：把对应文件改回 `.yml` 后提交。日常更新请不要同时开启 `daily.yml`，否则会与本地 publish 重复提交。

访客地图如需真实数据，推荐在本地生成：

```bash
python scripts/gen_visitors.py \
  --log /path/to/access.log \
  --mmdb /path/to/GeoLite2-City.mmdb \
  --days 90 \
  --out web/visitors.json
```

然后运行 `python metaweb.py publish --no-update --no-push` 部署。
