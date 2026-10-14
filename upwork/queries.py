"""GraphQL documents for www.upwork.com/api/graphql/v1, captured from the
site's own apps on 2026-10-14 (UniversalSearchNuxt, FreelancerProfileNuxt,
AgencyNuxt, CatalogApp). Each is sent with the Bearer token the owning app
sets as a cookie (upwork/fetch.py APPS)."""

# ---- UniversalSearchNuxt (jobs + talent search, suggestions) --------------------------------

_FACET = "{ key value }"

JOB_SEARCH = """
query VisitorJobSearch($requestVariables: VisitorJobSearchV1Request!) {
  search {
    universalSearchNuxt {
      visitorJobSearchV1(request: $requestVariables) {
        paging { total offset count }
        facets {
          jobType %(f)s workload %(f)s clientHires %(f)s durationV3 %(f)s
          amount %(f)s contractorTier %(f)s contractToHire %(f)s
        }
        results {
          id
          title
          description
          relevanceEncoded
          ontologySkills { uid parentSkillUid prefLabel prettyName: prefLabel freeText highlighted }
          jobTile {
            job {
              id
              ciphertext: cipherText
              jobType
              weeklyRetainerBudget
              hourlyBudgetMax
              hourlyBudgetMin
              hourlyEngagementType
              contractorTier
              sourcingTimestamp
              createTime
              publishTime
              hourlyEngagementDuration { rid label weeks mtime ctime }
              fixedPriceAmount { isoCurrencyCode amount }
              fixedPriceEngagementDuration { id rid label weeks ctime mtime }
            }
          }
        }
      }
    }
  }
}
""" % {"f": _FACET}

FREELANCER_SEARCH = """
query VisitorFreelancerSearch($request: VisitorFreelancerSearchV2Request!) {
  search {
    universalSearchNuxt {
      visitorFreelancerSearchV2(request: $request) {
        pagingInfo { total offset count originTotal pagesTotal page }
        adaptiveSkills { id prefLabel ontologyId }
        relevantSkillIds
        resultFlags { portfolioSearch }
        facets { hourlyRate { key value } }
        profiles {
          individualTotalEarnings
          agencyTotalEarnings
          offerConsultations
          jobSummariesAssignmentRids
          personId
          totalCompletedJobs
          rankInfo { d iv }
          vetted
          profile {
            identity { id ciphertext }
            personAvailability { purchasedInvitationBadge { active } }
            personalData {
              title firstName lastName description
              location { country state city region subregion timezone zip }
              chargeRate { rawValue currency }
              portrait { portrait100 }
              profileUrl
            }
            skills { ontologySkill { id preferredLabel prettyName definition } }
            projectList {
              totalProjects
              projects { id title projectUrl thumbnail category categoryId subCategory description videoUrl public }
            }
            verifications { idBadgeStatus idVerified }
            agencies {
              defaultAgencyId
              agencies { orgId ciphertext name classifications { id name } logo }
            }
            preferences { hideEarnings hideJss }
            profileAggregates {
              nSS100BwScore topRatedStatus topRatedPlusStatus totalHours totalHourlyJobs totalEarnings totalFixedJobs
            }
            communityCertificates { expirationDate }
          }
        }
      }
    }
  }
}
"""

SUGGESTIONS = """
query GetAutoSuggestions($request: UserUniversalSearchSuggestionInput!, $isUser: Boolean!) {
  allSuggestions(input: $request) {
    snippet
    suggestions { label: suggestion }
    peopleSuggestions @include(if: $isUser) { label: fullName }
  }
}
"""

RELATED_QUERIES = """
query GetRelatedQueries($request: RelatedQueriesInput!) {
  ufsRelatedQueries(input: $request) { relatedQueries query }
}
"""

CATEGORIES = """
query ontologyCategories {
  ontologyCategories {
    id preferredLabel ontologyId
    subcategories {
      id preferredLabel ontologyId
      services { id preferredLabel ontologyId }
    }
    services { id preferredLabel ontologyId }
  }
}
"""

# ---- FreelancerProfileNuxt (work history) ----------------------------------------------------

_WORK_HISTORY_FIELDS = """
  pageNumber itemsPerPage totalItems sortOrder filterClientAssignments
  assignments {
    node {
      startedOn endedOn totalHours type title description clientId isPrivate: private agencyName
      status hoursPerWeek id isEdc: edc ciphertext isPtc: ptc isOpeningVisible: openingVisible accessType openingHidden
      subtype openingUid: openingId clientTeamUid: clientTeamId highlighted contractHasNonzeroCharge traits
      clientInformation { clientTeamUid: clientTeamId name }
      totalCharges { node { amount currencyCode } }
      hourlyRate { node { amount currencyCode } }
      totalEarnings { node { amount currencyCode } }
      blendedChargeRate { node { amount currencyCode } }
      blendedEarnRate { node { amount currencyCode } }
      weeklyStipendChargeAmount { node { amount currencyCode } }
      initialAmount { node { amount currencyCode } }
      feedback { node {
        score comment commentIsPublic: commentPublic response scoreDetails { score label description }
        creationTs: creationTimeStamp id feedbackSuppressed publicFeedback } }
      feedbackGiven { node {
        score comment commentIsPublic: commentPublic response scoreDetails { score label description }
        creationTs: creationTimeStamp id feedbackSuppressed publicFeedback } }
      midContractFeedbacksAverage { node {
        score comment commentIsPublic: commentPublic response scoreDetails { score label description }
        creationTs: creationTimeStamp id feedbackSuppressed publicFeedback } }
      midContractFeedbacks { node {
        score comment commentIsPublic: commentPublic response scoreDetails { score label description }
        creationTs: creationTimeStamp id feedbackSuppressed publicFeedback } }
      skills { node {
        name prettyName active uid: id rank description externalUrl
        certificates { uid: id name description provider logoUrl verifier }
        ontologySkill { node { uid: id ontologyId prefLabel altLabel scopeNote externalLink definition comment entityStatus } }
      } }
      linkedPortfolio { node {
        uid: id title description rank url image thumbnail completedOn projectUrl
        videoUrl occupationUid: occupationId role projectGoal solution primaryImageUid: primaryImageId
        highlighted visibility skills projectType
        category { node { name urlSlug } } subCategory { node { name urlSlug } }
      } }
    }
  }
"""

# assignmentStates is an inline enum list ([Ended] / [InProgress]) because the
# enum type is not exposed to variables; the two documents are built from one
# template.
_WORK_HISTORY_TEMPLATE = """
query ($personId: String!, $pageNumber: Int, $itemsPerPage: Int, $sortBy: TalentVPDWorkHistorySort,
       $filterClientAssignments: Boolean, $excludeWithoutFeedback: Boolean, $excludeNoFeedbackComment: Boolean) {
  history: talentVPDAuthWorkHistory(filter: {
    personId: $personId
    pageNumber: $pageNumber
    itemsPerPage: $itemsPerPage
    sortBy: $sortBy
    filterClientAssignments: $filterClientAssignments
    assignmentStates: [%s]
    excludeWithoutFeedback: $excludeWithoutFeedback
    excludeNoFeedbackComment: $excludeNoFeedbackComment
  }) {
    node { %s }
  }
}
"""

WORK_HISTORY = {
    "completed": _WORK_HISTORY_TEMPLATE % ("Ended", _WORK_HISTORY_FIELDS),
    "in_progress": _WORK_HISTORY_TEMPLATE % ("InProgress", _WORK_HISTORY_FIELDS),
}

# ---- AgencyNuxt --------------------------------------------------------------------------------

AGENCY_LOCATIONS = """
query getAgencyLocations($orgId: ID!) {
  agencyLocations(orgId: $orgId) { locations { id country state city address zipCode } }
}
"""

AGENCY_MEMBERS = """
query getAgencyStaffs($agencyId: ID!, $agencyTeamId: ID!, $limit: Int, $offset: String) {
  agencyStaffs(agencyId: $agencyId, agencyTeamId: $agencyTeamId, limit: $limit, offset: $offset) {
    totalCount
    staffs {
      id agencyOwner memberType vetted active canBeViewed
      personalData { id rid name portrait ciphertext topRatedStatus topRatedPlusStatus jobSuccessScore profileAccess hideJss provider }
    }
  }
}
"""

AGENCY_PORTFOLIO = """
query getAgencyProjects($agencyId: ID!, $publicOnly: Boolean!, $offset: Int, $limit: Int, $categoryId: String) {
  organization {
    agency(id: $agencyId, publicOnly: $publicOnly) {
      projects(offset: $offset, limit: $limit, categoryUid: $categoryId, fullData: true) {
        totalCount
        pageInfo { hasNextPage endCursor }
        edges {
          cursor
          node {
            id title description thumbnail thumbnailId thumbnailOriginalId completionDateTime projectUrl
            categoryId rank skillIds
            attachments { id type title name size imageLarge imageMiddle originalFile originalFileId imageLargeId imageMiddleId imageSmallId }
          }
        }
      }
    }
  }
}
"""

AGENCY_WORK_HISTORY = """
query getAgencyUpWorkHistory($agencyId: ID!, $publicOnly: Boolean!, $type: [AgencyUpWorkHistoryType], $offset: Int, $limit: Int) {
  organization {
    agency(id: $agencyId, publicOnly: $publicOnly) {
      upWorkHistory(type: $type, offset: $offset, limit: $limit) {
        totalCount
        workHistoryList {
          title startedOnDateTime endedOnDateTime status totalCost totalHours totalCharges contractorEarnings
          hourlyRate hideEacEarnings jobType clientTeamUid ciphertext
          feedback { comment commentPublic feedbackSuppressed score details { label score weight } }
          feedbackGiven { comment commentPublic feedbackSuppressed score details { label score weight } }
        }
      }
    }
  }
}
"""

# ---- CatalogApp (project catalog) -----------------------------------------------------------

_TILE_FIELDS = """
  id
  data { title slug coverImageUrl priceStart priceEnd minDaysToFulfill status flowType }
  person { id ciphertext name portrait100 adjScore topRated topRatedPlus risingTalent totalFeedback detail { name } }
  coverMedia { id type url metadataJson }
  images { id smallImagesUrl }
  videos { id type metadataJson }
  documents { id type metadataJson }
"""

CATALOG_SEARCH = """
query visitorSearchCatalogV4($request: VcsV4Request!) {
  search {
    universalSearchNuxt {
      visitorCatalogSearchV4(request: $request) {
        paging { total nextCursorMark count }
        projects {
          imageCoverMediaToShowId
          projectTile { %s }
        }
      }
    }
  }
}
""" % _TILE_FIELDS

CATALOG_FACETS = """
query searchVisitorV4Facets($VisitorV4FacetsRequest: VcsV4FacetsRequest!) {
  search {
    universalSearchNuxt {
      visitorCatalogSearchV4Facets(request: $VisitorV4FacetsRequest) {
        projectCategoryL4Facets { allCount facets { count id } }
        deliveryTimeFacets { anyTime lessThan1Day lessThan7Days lessThan21Days }
        talentDetailsFacets {
          anyEnglishProficiencyLevelRank anyRating englishProficiencyLevelRank1 englishProficiencyLevelRank2
          englishProficiencyLevelRank3 englishProficiencyLevelRank4 risingTalent topRated topRatedPlus
          upRating2 upRating3 upRating4
        }
      }
    }
  }
}
"""

CATALOG_SUGGESTIONS = """
query projectSuggestions($input: SuggestionSearchInput!) {
  projectSuggestions(input: $input) { suggestions { suggestion: suggestionText frequency } }
}
"""

CATALOG_RELATED = """
query relatedQueriesV1($query: String!) {
  search { catalogApp { relatedQueriesV1(request: { query: $query }) { relatedQueries } } }
}
"""

CATALOG_SELLER_PROJECTS = """
query browseCatalogProjectTilesForActiveFreelancers($request: ProjectsCatalogFilter!) {
  browseCatalogProjectTilesForActiveFreelancers(filter: $request) { projectTiles { %s } }
}
""" % _TILE_FIELDS

CATALOG_SIMILAR = """
query searchVisitorMoreLikeThisV2($visitorMoreLikeThisV2Request: VisitorMoreLikeThisV2Request!) {
  search {
    catalogProjectDetailsNuxt {
      visitorMoreLikeThisV2(request: $visitorMoreLikeThisV2Request) { projects { projectTile { %s } } }
    }
  }
}
""" % _TILE_FIELDS

FEEDBACK_STATISTICS = """
query FreelancerFeedBackStatistics($freelancerId: ID!) {
  freelancerFeedBackStatistics(freelancerId: $freelancerId) {
    freelancerId totalCountOfRates averageScore
    distributions { rate count }
    detailsDistributions { name averageScore }
  }
}
"""
