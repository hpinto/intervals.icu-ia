rclone sync -P /opt/intervals.icu GoogleDrive:/intervals.icu --config /root/.config/rclone/rclone.conf --transfers 4 --checkers 8 --tpslimit 10 --drive-chunk-size 32M
