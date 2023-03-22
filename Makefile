CURL=curl -LSs
JSON=-H 'content-type: application/json'
HOST=localhost:9200
INDEX=brinta

TR=https://textrepo.republic-caf.diginfra.org/api
URL_1728=${tr}/task/find/volume-1728/file/contents?type=segmented_text

# docker management
docker-image: Dockerfile
	docker build -t brinta .

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
	@$(CURL) $(JSON) $(HOST)/$(INDEX)/_search -d @query.json \
		| jq .
