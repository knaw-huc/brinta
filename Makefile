CURL=curl -LSs
JSON=-H 'content-type: application/json'
HOST=localhost:9200
INDEX=resolutions

TR=https://textrepo.republic-caf.diginfra.org/api
URL_1728=$(TR)/task/find/volume-1728/file/contents?type=segmented_text

# docker management
docker-image: Dockerfile
	docker build -t brinta .

TAG := brinta:8.14.1
LOCAL_TAG := $(TAG)
REMOTE_TAG := registry.diginfra.net/tt/$(TAG)

push: docker-image
	docker build --tag $(LOCAL_TAG) --platform=linux/amd64 --file Dockerfile .
	docker tag $(LOCAL_TAG) $(REMOTE_TAG)
	docker push $(REMOTE_TAG)

start-server: docker-image
	docker-compose up -d

stop-server:
	docker-compose down

show-logs:
	docker-compose logs -f


# index management
create-index:
	@$(CURL) -XPUT $(JSON) $(HOST)/$(INDEX) -d @mapping.json \
		| jq .

delete-index:
	@$(CURL) -XDELETE $(HOST)/$(INDEX) \
		| jq .



# volume 1728 specific

cat-1728:
	@$(CURL) $(URL_1728)

index-1728:
	@$(CURL) $(URL_1728) \
		| jq '{text: ._ordered_segments}' \
		| $(CURL) -XPUT $(JSON) $(HOST)/$(INDEX)/_doc/volume-1728 -d @- \
		| jq .

delete-1728:
	@$(CURL) -XDELETE $(HOST)/$(INDEX)/_doc/volume-1728 \
		| jq .

query-1728:
	@$(CURL) $(JSON) $(HOST)/$(INDEX)/_search -d @match-query.json \
		| jq .

query-tanda-1728:
	@$(CURL) $(JSON) $(HOST)/$(INDEX)/_search -d @text-and-date.json \
		| jq .
