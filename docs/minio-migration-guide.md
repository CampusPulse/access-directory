
podman volume export accessdirectory_minio-data >miniodata.tar
podman volume create accessdirectory_silo-data

podman volume import accessdirectory_silo-data ./miniodata.tar