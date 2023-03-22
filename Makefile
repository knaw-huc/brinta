CURL=curl -LSs

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
	@$(CURL) -XPUT -H 'content-type: application/json' localhost:9200/$(INDEX) -d @mapping.json \
		| jq .

delete-index:
	@$(CURL) -XDELETE localhost:9200/$(INDEX) \
		| jq .



# volume 1728 specific

cat-1728:
	@$(CURL) $(URL_1728)

index-1728:
	@$(CURL) $(URL_1728) \
		| jq '{text: ._ordered_segments}' \
		| $(CURL) -XPUT -H 'content-type: application/json' localhost:9200/$(INDEX)/_doc/volume-1728 -d @- \
		| jq .

delete-1728:
	@$(CURL) -XDELETE localhost:9200/$(INDEX)/_doc/volume-1728 \
		| jq .

query-1728:
	@$(CURL) -H 'content-type: application/json' localhost:9200/$(INDEX)/_search -d @query.json \
		| jq .
