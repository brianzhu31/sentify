import os
import json
import openai
import requests
from dotenv import load_dotenv
from newscatcherapi import NewsCatcherApiClient
from openai import OpenAI
from app.util.prompt import get_relevant_articles_prompt, get_analysis_prompt
from app.util.text import clean_text

load_dotenv()

NEWSCATCHER_KEY = os.getenv("NEWSCATCHER_KEY")
OPENAI_KEY = os.getenv("OPENAI_KEY")

client = OpenAI(
    api_key=OPENAI_KEY,
)


def get_news(company_name: str, ticker: str, days_ago: int) -> dict:
    newscatcherapi = NewsCatcherApiClient(x_api_key=NEWSCATCHER_KEY)

    news_articles = newscatcherapi.get_search(
        q=f'"{company_name}" OR "{ticker}"', lang="en", from_=f"{days_ago} days ago",
        to_rank=500, page_size=100
    )

    return news_articles


def get_relevant_articles(company_name: str, news_articles: dict) -> dict:
    article_previews = ""
    for i, article in enumerate(news_articles["articles"]):
        article_title = article["title"]
        article_excerpt = article["excerpt"]
        article_previews += f"<Article preview {i}>\nArticle title: {article_title}\nArticle excerpt: {article_excerpt}\n</Article preview {i}>\n\n"

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        temperature=0,
        top_p=0.1,
        max_tokens=4096,
        messages=get_relevant_articles_prompt(company_name, article_previews)
    )

    output = response.choices[0].message.content
    json_output = json.loads(output)

    return json_output["data"]


def create_filtered_articles_content(news_articles: dict, relevant_articles: dict) -> str:
    filtered_articles_content = ""
    set_of_relevant_articles = set(relevant_articles)
    set_of_article_titles = set()

    for i, article in enumerate(news_articles["articles"]):
        article_title = article["title"]
        if i in set_of_relevant_articles and article_title not in set_of_article_titles:
            article_content = clean_text(article["summary"])[:4500]
            filtered_articles_content += f"<Article {i}>\nArticle title: {article_title}\nArticle content:\n{article_content}\n</Article {i}>\n\n"
            set_of_article_titles.add(article_title)

    return filtered_articles_content


def get_analysis(company_name: str, filtered_articles: str, relevant_articles: list) -> dict:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        temperature=0.2,
        top_p=0.9,
        messages=get_analysis_prompt(
            company_name, filtered_articles, relevant_articles)
    )
    output = response.choices[0].message.content
    json_output = json.loads(output)

    return json_output


def format_analysis(analysis_data: dict, news_articles: dict) -> dict:
    formatted_output = {}
    set_of_sources = set()
    list_of_top_sources = []

    def traverse_key_points(category: str):
        list_of_key_points = []
        for point in analysis_data[category]:
            article_index = point["source"]
            list_of_key_points.append({
                "summary": point["summary"],
                "source": {
                    "title": news_articles["articles"][article_index]["title"],
                    "link": news_articles["articles"][article_index]["link"]
                }
            })
            if article_index not in set_of_sources:
                list_of_top_sources.append({
                    "article_title": news_articles["articles"][article_index]["title"],
                    "article_link": news_articles["articles"][article_index]["link"]
                })
                set_of_sources.add(article_index)
        formatted_output[category] = list_of_key_points

    traverse_key_points("positive")
    traverse_key_points("negative")

    formatted_output["top_sources"] = list_of_top_sources

    def sentiment_to_int_score(sentiment):
        mapping = {
            "VERY NEGATIVE": 1,
            "NEGATIVE": 2,
            "NEUTRAL": 3,
            "POSITIVE": 4,
            "VERY POSITIVE": 5
        }
        return mapping.get(sentiment, 3)

    def impact_to_int_score(impact):
        mapping = {
            "LOW": 1,
            "MEDIUM": 3,
            "HIGH": 5
        }
        return mapping.get(impact, 1)

    total_score = 0
    total_weight = 0
    for rating in analysis_data["ratings"]:
        int_score = sentiment_to_int_score(rating["sentiment"])
        int_weight = impact_to_int_score(rating["impact"])
        total_score += int_score * int_weight
        total_weight += int_weight

    overall_score = total_score/total_weight if total_weight != 0 else 0

    formatted_output["score"] = round(overall_score)

    return formatted_output


def get_company_analysis_data(company_name: str, ticker: str, days_ago: int) -> dict:
    raw_news_data = get_news(company_name, ticker, days_ago)
    relevant_news_articles = get_relevant_articles(company_name, raw_news_data)
    filtered_articles_content = create_filtered_articles_content(
        raw_news_data, relevant_news_articles)
    analysis_data = get_analysis(
        company_name, filtered_articles_content, relevant_news_articles)
    with open("relevant_articles.json", "w", encoding="utf-8") as json_file:
        json.dump(relevant_news_articles, json_file, indent=4)
    with open("app_output.json", "w", encoding="utf-8") as json_file:
        json.dump(analysis_data, json_file, indent=4)
    formatted_analysis = format_analysis(analysis_data, raw_news_data)
    return formatted_analysis
